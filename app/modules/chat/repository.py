"""
repository.py — Database access layer for the chat module.

Design principles
─────────────────
1. **Public ID only at the boundary** — external callers pass/receive `public_id`;
   internal joins always use the integer-like `id` PK for speed.

2. **No N+1** — every query that needs related rows uses `selectinload` (batched
   SELECT … IN) or `contains_eager` (JOIN + loaded together). The ORM
   `lazy="select"` on relationships is a safety net, not the loading strategy.

3. **Keyset (cursor) pagination** — `get_conversations` uses `(created_at, public_id)`
   as the pagination key instead of OFFSET so performance stays O(log n) at
   any page depth. Cursor is encoded as "<iso_datetime>|<public_id>".

4. **Minimal DB round-trips** — count and page queries are sent concurrently
   where possible; messages are fetched in one batched query per conversation set.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.utils.hashing_utils import hash_identity

from .models import Conversation, ConversationStatus, Message, MessageRole

from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime, timezone
from .models import ConversationInsights
from app.config.settings import get_settings

settings = get_settings()
CHAT_PREVIOUS_CONVERSATION_SESSION_LIMIT = settings.CHAT_PREVIOUS_CONVERSATION_SESSION_LIMIT
# ---------------------------------------------------------------------------
# Cursor helpers
# ---------------------------------------------------------------------------

_CURSOR_SEP = "|"


def encode_cursor(created_at: datetime, public_id: str) -> str:
    """Encode a (created_at, public_id) pair into an opaque base64 cursor."""
    raw = f"{created_at.isoformat()}{_CURSOR_SEP}{public_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> Tuple[datetime, str]:
    """Decode a cursor back into (created_at, public_id)."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        iso, public_id = raw.split(_CURSOR_SEP, 1)
        return datetime.fromisoformat(iso), public_id
    except Exception as exc:
        raise ValueError(f"Invalid pagination cursor: {cursor!r}") from exc


# ---------------------------------------------------------------------------
# Conversation — writes
# ---------------------------------------------------------------------------

async def get_or_create_conversation(
    db: AsyncSession,
    *,
    conversation_public_id: Optional[str],
    tenant_id: str,
    chatbot_config_id: Optional[int] = None,
) -> Tuple[Conversation, bool]:
    """
    Look up an existing conversation by its public_id, or create a new one.

    Returns (conversation, is_new).
    Raises ValueError if the public_id is provided but not found (prevents
    clients from silently creating duplicate conversations).

    chatbot_config_id is set for widget conversations (looked up via iframe_token)
    and NULL for legacy/admin conversations.
    """
    if conversation_public_id:
        result = await db.execute(
            select(Conversation).where(
                Conversation.public_id == conversation_public_id,
                Conversation.tenant_id == tenant_id,
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            logger.warning("[chat] get_or_create_conversation not found public_id=%s tenant=%s", conversation_public_id, tenant_id)
            raise ValueError(
                f"Conversation '{conversation_public_id}' not found for this tenant."
            )
        logger.debug("[chat] get_or_create_conversation existing public_id=%s tenant=%s", conversation_public_id, tenant_id)
        return conversation, False

    # New conversation — flush so we get the generated id/public_id immediately
    conversation = Conversation(
        tenant_id=tenant_id,
        chatbot_config_id=chatbot_config_id,
    )
    db.add(conversation)
    await db.flush()
    logger.info("[chat] conversation created public_id=%s tenant=%s", conversation.public_id, tenant_id)
    return conversation, True


async def get_conversation_by_public_id(
    db: AsyncSession,
    *,
    conversation_public_id: str,
    tenant_id: str,
) -> Conversation | None:

    if not conversation_public_id:
        return None

    result = await db.execute(
        select(Conversation).where(
            Conversation.public_id == conversation_public_id,
            Conversation.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()

async def update_conversation_activity(
    conversation: Conversation,
    *,
    message_increment: int = 0,
    token_increment: int = 0,
) -> None:
    """Bump counters and refresh last_activity_at. No DB call needed here
    because the object is already in the session — the commit will flush it."""
    conversation.total_messages += message_increment
    conversation.total_tokens_used += token_increment
    conversation.last_activity_at = datetime.now(timezone.utc)


async def update_conversation_status(
        db: AsyncSession,
        *,
        conversation__id: str,
        tenant_id: str,
        status: ConversationStatus) -> None:
    logger.info("[chat] conversation status updated tenant=%s new_status=%s", tenant_id, status)
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conversation__id, Conversation.tenant_id == tenant_id)
        .values(status=status)
    )


# ---------------------------------------------------------------------------
# Conversation — reads
# ---------------------------------------------------------------------------

async def get_conversations(
    db: AsyncSession,
    *,
    tenant_id: str,
    page_size: int,
    cursor: Optional[str] = None,
    status: Optional[ConversationStatus] = None,
) -> Tuple[List[Conversation], Optional[str], int]:
    """
    Keyset-paginated list of conversations (no messages loaded — list view only).

    Returns (conversations, next_cursor, total_count).

    Keyset strategy
    ───────────────
    Sort order: (created_at DESC, public_id DESC)  — stable even when two rows
    share the same millisecond timestamp.

    The WHERE clause for pages 2+ becomes:
        (created_at, public_id) < (cursor_dt, cursor_pid)   [for DESC order]

    This translates to:
        created_at < cursor_dt
        OR (created_at = cursor_dt AND public_id < cursor_pid)

    The composite index ix_conversations_tenant_cursor makes this a fast
    index seek rather than a full scan + sort.
    """
    # ── Base filter ──────────────────────────────────────────────────────────
    filters = [Conversation.tenant_id == tenant_id]
    if status:
        filters.append(Conversation.status == status)

    # ── Cursor filter ─────────────────────────────────────────────────────────
    if cursor:
        cursor_dt, cursor_pid = decode_cursor(cursor)
        filters.append(
            or_(
                Conversation.created_at < cursor_dt,
                and_(
                    Conversation.created_at == cursor_dt,
                    Conversation.public_id < cursor_pid,
                ),
            )
        )

    base_where = and_(*filters)

    # ── Count (total, ignoring cursor) ────────────────────────────────────────
    # We re-run without the cursor filter so the total always reflects the
    # whole tenant dataset, not just "records after the cursor".
    count_filters = [Conversation.tenant_id == tenant_id]
    if status:
        count_filters.append(Conversation.status == status)

    total_result = await db.execute(
        select(func.count())
        .select_from(Conversation)
        .where(and_(*count_filters))
    )
    total: int = total_result.scalar_one()
    logger.debug("[chat] get_conversations tenant=%s total=%d page_size=%d cursor=%s", tenant_id, total, page_size, bool(cursor))

    # ── Page query ────────────────────────────────────────────────────────────
    # Fetch page_size + 1 to know whether a next page exists without a
    # second COUNT query.
    rows_result = await db.execute(
        select(Conversation)
        .where(base_where)
        .order_by(Conversation.created_at.desc(), Conversation.public_id.desc())
        .limit(page_size + 1)
        # No selectinload — list view never needs messages
    )
    rows: List[Conversation] = list(rows_result.scalars().all())

    has_next = len(rows) > page_size
    if has_next:
        rows = rows[:page_size]

    next_cursor: Optional[str] = None
    if has_next and rows:
        last = rows[-1]
        next_cursor = encode_cursor(last.created_at, last.public_id)

    return rows, next_cursor, total


async def get_conversation_detail(
    db: AsyncSession,
    *,
    public_id: str,
    tenant_id: str,
) -> Optional[Conversation]:
    """
    Fetch a single conversation with ALL messages in exactly 2 SQL queries:
      1. SELECT conversation WHERE public_id = …
      2. SELECT messages WHERE conversation_id IN (…)   ← batched by selectinload

    selectinload is preferred over joinedload here because joinedload would
    produce a wide Cartesian JOIN and duplicate the conversation columns for
    every message row — wasteful for long conversations.
    """
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.public_id == public_id,
            Conversation.tenant_id == tenant_id,
        )
        .options(
            selectinload(Conversation.messages)  # 2nd query, no N+1
        )
    )
    return result.scalar_one_or_none()


async def get_conversation_history(
    db: AsyncSession,
    *,
    conversation__id: int,          # internal PK — fast
    limit: Optional[int] = None,   # None = all; set to cap LLM context window
) -> List[Message]:
    """
    Fetch raw message rows for LLM context building.

    Uses the internal PK (not public_id) because this is an internal call
    from the service layer that already has the Conversation object.
    Ordered oldest-first so they can be passed directly to the LLM.
    """
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation__id)
        .order_by(Message.created_at.asc())
    )
    if limit:
        stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_previous_sessions_by_identity(
    db: AsyncSession,
    *,
    identity_hash: str,
    exclude_conversation_id: int,
    tenant_id: str,
) -> list[Conversation]:
    """
    Fetch all previous closed conversations for a given identity hash.
    Excludes the current conversation.
    Ordered newest first so ARIA sees most recent context at the top.
    Capped at 5 — no need to send ARIA 20 sessions worth of summaries.
    """
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.identity_hash == identity_hash,
            Conversation.tenant_id == tenant_id,
            Conversation.id != exclude_conversation_id,
            Conversation.status.in_([
                ConversationStatus.closed,
                ConversationStatus.summarized,
                ConversationStatus.emailed,
                ConversationStatus.archived,
            ]),
            Conversation.summary.isnot(None),
        )
        .order_by(Conversation.created_at.desc())
        .limit(CHAT_PREVIOUS_CONVERSATION_SESSION_LIMIT)
    )
    return result.scalars().all()

# ---------------------------------------------------------------------------
# Message — writes
# ---------------------------------------------------------------------------

async def add_message(
    db: AsyncSession,
    *,
    conversation_id: str,   # internal PK
    role: MessageRole,
    content: str,
    tokens_used: Optional[int] = None,
    model_used:  Optional[str] = None,
    response_ms: Optional[int] = None,
) -> Message:
    """
    Insert a single message and flush so `public_id` / `id` are populated
    before the caller uses them in the response.
    """
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        tokens_used=tokens_used,
        model_used=model_used,
        response_ms=response_ms,
    )
    db.add(message)
    await db.flush()   # populate defaults (public_id, id, created_at)
    return message


async def add_messages(
    db: AsyncSession,
    *,
    messages: list[Message],
) -> list[Message]:

    db.add_all(messages)
    await db.flush()
    return messages

# ---------------------------------------------------------------------------
# Conversation Insights — writes
# ---------------------------------------------------------------------------

async def upsert_conversation_insights(
    db: AsyncSession,
    *,
    conversation__id: int,
    tenant_id: str,
    insights: dict,
    lead_data: Optional[dict] = None,
) -> ConversationInsights:
    """
    Upsert conversation insights and update the parent conversation
    with lead data — all in one transaction.

    insights: the "insights" dict from the OpenAI response
    lead_data: the "lead" dict from the OpenAI response (name, email, phone)
    """
    now = datetime.now(timezone.utc)

    # ── 1. Upsert insights ───────────────────────────────────────────────────
    stmt = (
        pg_insert(ConversationInsights)
        .values(
            conversation_id=conversation__id,
            tenant_id=tenant_id,
            lead_score=insights.get("lead_score"),
            lead_tier=insights.get("lead_tier"),
            intent=insights.get("intent"),
            budget_min=insights.get("budget_min"),
            budget_max=insights.get("budget_max"),
            budget_currency=insights.get("budget_currency"),
            suburbs_mentioned=insights.get("suburbs_mentioned"),
            cities_mentioned=insights.get("cities_mentioned"),
            property_types=insights.get("property_types"),
            bedrooms_wanted=insights.get("bedrooms_wanted"),
            timeline=insights.get("timeline"),
            sentiment=insights.get("sentiment"),
            engagement_score=insights.get("engagement_score"),
            topics_mentioned=insights.get("topics_mentioned"),
            ai_summary=insights.get("ai_summary"),
            ai_insights=insights.get("ai_insights"),
            processed_at=now,
            processing_version=insights.get("processing_version", "v1.0"),
        )
        .on_conflict_do_update(
            index_elements=["conversation_id"],
            set_=dict(
                lead_score=insights.get("lead_score"),
                lead_tier=insights.get("lead_tier"),
                intent=insights.get("intent"),
                budget_min=insights.get("budget_min"),
                budget_max=insights.get("budget_max"),
                budget_currency=insights.get("budget_currency"),
                suburbs_mentioned=insights.get("suburbs_mentioned"),
                cities_mentioned=insights.get("cities_mentioned"),
                property_types=insights.get("property_types"),
                bedrooms_wanted=insights.get("bedrooms_wanted"),
                timeline=insights.get("timeline"),
                sentiment=insights.get("sentiment"),
                engagement_score=insights.get("engagement_score"),
                topics_mentioned=insights.get("topics_mentioned"),
                ai_summary=insights.get("ai_summary"),
                ai_insights=insights.get("ai_insights"),
                processed_at=now,
                processing_version=insights.get("processing_version", "v1.0"),
            )
        )
        .returning(ConversationInsights)
    )

    result = await db.execute(stmt)
    saved = result.scalars().first()

    # ── 2. Update conversation with lead data ────────────────────────────────
    if lead_data:
        lead_name = lead_data.get("name")
        lead_email = lead_data.get("email")
        lead_phone = lead_data.get("phone")
        ai_summary = insights.get("ai_summary")

        # Only mark as lead if we actually got identifying info
        # is_lead = any([lead_name, lead_email, lead_phone, ai_summary])
        is_lead = all([lead_name, lead_email, lead_phone])

        await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation__id)
            .values(
                is_lead=is_lead,
                lead_name=lead_name,
                lead_email=lead_email,
                lead_phone=lead_phone,
                identity_hash=(
                    hash_identity(lead_email) if lead_email
                    else hash_identity(lead_phone) if lead_phone
                    else None
                ),
                summary=ai_summary,
                status=ConversationStatus.summarized
            )
        )

    # ── 3. Commit both together ──────────────────────────────────────────────
    await db.commit()
    logger.info("[chat] insights upserted tenant=%s is_lead=%s lead_score=%s", tenant_id, lead_data and all([lead_data.get("name"), lead_data.get("email"), lead_data.get("phone")]), insights.get("lead_score"))
    return saved



async def upsert_website_conversation_insights(
    db: AsyncSession,
    *,
    conversation__id: int,
    tenant_id: str,
    insights: dict,
    lead_data: Optional[dict] = None,
) -> ConversationInsights:
    """
    Upsert conversation insights for Veloce WEBSITE (B2B) conversations
    and update the parent conversation with lead data — all in one transaction.

    This method handles the getveloce.com website chatbot context where
    the visitor is a real estate professional evaluating Veloce/ARIA for
    their business — NOT a property buyer.

    Column remapping vs the property chatbot:
    ─────────────────────────────────────────
      budget_min        → always None  (not applicable)
      budget_max        → always None  (not applicable)
      budget_currency   → subscription preference: "monthly" | "annual" | None
      suburbs_mentioned → pain points string array
      cities_mentioned  → business operating locations string array
      property_types    → business type as single-item string array
      bedrooms_wanted   → always None  (not applicable)

    insights : the "insights" dict from the LLM response (Veloce website prompt)
    lead_data: the "lead" dict from the LLM response (name, email, phone)
    """
    now = datetime.now(timezone.utc)

    # ── Remap B2B fields from their repurposed column names ──────────────────
    # These clarify intent at the call site — the DB columns are shared,
    # but the semantics differ between chatbot contexts.
    subscription_preference = insights.get("budget_currency")   # "monthly" | "annual" | None
    pain_points             = insights.get("suburbs_mentioned")  # string[] | None
    business_locations      = insights.get("cities_mentioned")   # string[] | None
    business_type           = insights.get("property_types")     # ["real_estate_agency"] | None

    # ── 1. Upsert insights ───────────────────────────────────────────────────
    stmt = (
        pg_insert(ConversationInsights)
        .values(
            conversation_id     = conversation__id,
            tenant_id           = tenant_id,
            lead_score          = insights.get("lead_score"),
            lead_tier           = insights.get("lead_tier"),
            intent              = insights.get("intent"),

            # Not applicable in B2B context — always None
            budget_min          = None,
            budget_max          = None,
            bedrooms_wanted     = None,

            # Repurposed columns — B2B semantics
            budget_currency     = subscription_preference,
            suburbs_mentioned   = pain_points,
            cities_mentioned    = business_locations,
            property_types      = business_type,

            timeline            = insights.get("timeline"),
            sentiment           = insights.get("sentiment"),
            engagement_score    = insights.get("engagement_score"),
            topics_mentioned    = insights.get("topics_mentioned"),
            ai_summary          = insights.get("ai_summary"),
            ai_insights         = insights.get("ai_insights"),
            processed_at        = now,
            processing_version  = insights.get("processing_version", "v1.0-website"),
        )
        .on_conflict_do_update(
            index_elements=["conversation_id"],
            set_=dict(
                lead_score          = insights.get("lead_score"),
                lead_tier           = insights.get("lead_tier"),
                intent              = insights.get("intent"),

                budget_min          = None,
                budget_max          = None,
                bedrooms_wanted     = None,

                budget_currency     = subscription_preference,
                suburbs_mentioned   = pain_points,
                cities_mentioned    = business_locations,
                property_types      = business_type,

                timeline            = insights.get("timeline"),
                sentiment           = insights.get("sentiment"),
                engagement_score    = insights.get("engagement_score"),
                topics_mentioned    = insights.get("topics_mentioned"),
                ai_summary          = insights.get("ai_summary"),
                ai_insights         = insights.get("ai_insights"),
                processed_at        = now,
                processing_version  = insights.get("processing_version", "v1.0-website"),
            )
        )
        .returning(ConversationInsights)
    )

    result = await db.execute(stmt)
    saved  = result.scalars().first()

    # ── 2. Update conversation with lead data ────────────────────────────────
    if lead_data:
        lead_name  = lead_data.get("name")
        lead_email = lead_data.get("email")
        lead_phone = lead_data.get("phone")
        ai_summary = insights.get("ai_summary")

        # Website leads: mark as lead only when all three identifiers are present.
        # B2B visitors often share email/phone at end of conversation — requiring
        # all three avoids flagging partial contacts as qualified leads.
        is_lead = all([lead_name, lead_email, lead_phone])

        await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation__id)
            .values(
                is_lead    = is_lead,
                lead_name  = lead_name,
                lead_email = lead_email,
                lead_phone = lead_phone,
                identity_hash=(
                    hash_identity(lead_email) if lead_email
                    else hash_identity(lead_phone) if lead_phone
                    else None
                ),
                summary    = ai_summary,
                status     = ConversationStatus.summarized,
            )
        )

    # ── 3. Commit both together ──────────────────────────────────────────────
    await db.commit()
    logger.info("[chat] website insights upserted tenant=%s is_lead=%s lead_score=%s", tenant_id, lead_data and all([lead_data.get("name"), lead_data.get("email"), lead_data.get("phone")]), insights.get("lead_score"))
    return saved


# ---------------------------------------------------------------------------
# Corn jobs — fetching idle conversations for analysis
# ---------------------------------------------------------------------------

async def get_idle_conversations(
    db: AsyncSession,
    idle_before: datetime,
) -> list[tuple[int, str]]:
    """
    Return (id, tenant_id) pairs for every in_progress conversation
    that has had no activity since `idle_before`.

    Excludes conversations that are already being processed
    (status != in_progress) so a slow worker never double-fires.
    """
    result = await db.execute(
        select(Conversation.id, Conversation.tenant_id)
        .where(
            Conversation.status == ConversationStatus.in_progress,
            Conversation.last_activity_at < idle_before,
        )
    )
    return result.all()          # list of Row(id, tenant_id)


async def get_idle_conversations(
    db: AsyncSession,
    idle_before: datetime,
) -> list:
    """
    Returns all in_progress conversations with no activity since idle_before.
    Used exclusively by the idle-conversation cron job.
    """
    result = await db.execute(
        select(Conversation.id, Conversation.tenant_id)
        .where(
            Conversation.status == ConversationStatus.in_progress,
            Conversation.last_activity_at < idle_before,
        )
    )
    rows = result.all()
    logger.debug("[chat] get_idle_conversations found count=%d idle_before=%s", len(rows), idle_before.isoformat())
    return rows


async def get_idle_conversations_batch(
    db: AsyncSession,
    idle_before: datetime,
    after_id: int,       # keyset cursor — start after this internal id
    limit: int = 100,
) -> list:
    result = await db.execute(
        select(Conversation.id, Conversation.tenant_id)
        .where(
            Conversation.status == ConversationStatus.in_progress,
            Conversation.last_activity_at < idle_before,
            Conversation.id > after_id,   # keyset — no OFFSET
        )
        .order_by(Conversation.id)        # must order for keyset to be stable
        .limit(limit)
    )
    rows = result.all()
    logger.debug("[chat] get_idle_conversations_batch found count=%d limit=%d", len(rows), limit)
    return rows
