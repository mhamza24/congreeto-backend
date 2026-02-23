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
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Conversation, ConversationStatus, Message, MessageRole


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
) -> Tuple[Conversation, bool]:
    """
    Look up an existing conversation by its public_id, or create a new one.

    Returns (conversation, is_new).
    Raises ValueError if the public_id is provided but not found (prevents
    clients from silently creating duplicate conversations).
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
            raise ValueError(
                f"Conversation '{conversation_public_id}' not found for this tenant."
            )
        return conversation, False

    # New conversation — flush so we get the generated id/public_id immediately
    conversation = Conversation(tenant_id=tenant_id)
    db.add(conversation)
    await db.flush()
    return conversation, True


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
    conversation_id: str,          # internal PK — fast
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
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    if limit:
        stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    return list(result.scalars().all())


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
