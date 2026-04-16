"""
service.py — Business logic layer for the chat module.

Responsibilities
────────────────
- Resolve the chatbot from the widget's iframe_token (no more hardcoded tenant_id).
- Enforce billing limits (conversations quota + token quota) before processing.
- Run hybrid RAG retrieval (vector + full-text + listing semantic search) for
  every user message and inject the results into the LLM context.
- Assemble the final system prompt: static base (pre-built personality + company
  profile) + dynamic suffix (RAG chunks + time awareness + returning visitor).
- Track token usage per message and update both the conversation counter and
  the billing UsageRecord so quota enforcement stays accurate.
- Own the DB transaction boundary (commit lives here, not in the router).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UsageMetric
from app.modules.billing.task_helpers import (
    can_start_new_conversation,
    can_continue_conversation,
    increment_and_check,
)
from app.modules.campaigns import repository as campaign_repo
from app.modules.chat import tasks as background_tasks
from app.modules.chatbot import repository as chatbot_repo
from app.modules.chatbot import service as chatbot_service
from app.modules.open_ai import service as openai_service
from app.utils.email_extractor import extract_and_validate_identity
from app.utils.hashing_utils import hash_identity
from app.utils.system_prompt_generator import build_campaign_overlays_block, build_dynamic_context
from app.utils.system_prompt_time_awareness import get_time_awareness_prompt
from app.utils.system_prompt_previous_sessions import get_returning_visitor_prompt

from app.config.settings import get_settings

from . import repository as repo
from . import schemas
from .models import ConversationStatus, Message, MessageRole

logger = logging.getLogger(__name__)
_settings = get_settings()

# ---------------------------------------------------------------------------
# Billing limit message — shown to widget visitors when the tenant quota runs out
# ---------------------------------------------------------------------------

_BILLING_LIMIT_MESSAGE = (
    "We are not taking new enquiries through this chat at the moment. "
    "Please reach out through the contact details on this page and we will get back to you shortly."
)

# RAG retrieval sizes — controlled via settings.py so they can be tuned per-env.
_RAG_TOP_K = _settings.RAG_TOP_K
_LISTING_TOP_K = _settings.RAG_LISTING_TOP_K

# Chat / billing constants — all sourced from settings, no magic numbers here.
_CHAT_HISTORY_LIMIT = _settings.CHAT_HISTORY_LIMIT
_DEFAULT_MAX_TOKENS = _settings.BILLING_DEFAULT_MAX_TOKENS_PER_MONTH
_DEFAULT_MAX_CONVERSATIONS = _settings.BILLING_DEFAULT_MAX_CONVERSATIONS_PER_MONTH

# Max user turns to include in the synthesized RAG query.
# Keeps the embedding input bounded even for very long conversations.
_RAG_QUERY_USER_TURNS = 8


# ---------------------------------------------------------------------------
# 1. Chat — create or continue  (main widget endpoint)
# ---------------------------------------------------------------------------

async def create_or_continue_chat(
    db: AsyncSession,
    *,
    payload: schemas.ChatCreateRequest,
) -> schemas.ChatReplyResponse:

    logger.info("[chat] create_or_continue_chat iframe_token=%s conversation_id=%s", payload.iframe_token, payload.conversation_id or "new")

    # ── 1. Resolve chatbot via iframe_token ─────────────────────────────────
    chatbot = await chatbot_repo.get_chatbot_by_iframe_token(
        db, iframe_token=payload.iframe_token
    )
    if chatbot is None:
        logger.warning("[chat] chatbot not found iframe_token=%s", payload.iframe_token)
        raise ValueError("Chatbot not found. Check the iframe_token.")

    if chatbot.status != "active":
        # Chatbot is draft or inactive — return a polite unavailable message
        return schemas.ChatReplyResponse(
            conversation_id="",
            message_id="",
            role=MessageRole.assistant,
            content=_BILLING_LIMIT_MESSAGE,
        )

    # Integer tenant PK — used for all billing operations
    tenant_db_id: int = chatbot.tenant_id
    # String tenant ref — stored in Conversation.tenant_id for admin list queries
    tenant_str: str = str(tenant_db_id)

    # ── 2. Billing gate — new conversation quota ────────────────────────────
    is_new_request = not payload.conversation_id
    if is_new_request:
        allowed, _, _, _ = await can_start_new_conversation(
            db, tenant_id=tenant_db_id
        )
        if not allowed:
            logger.info(f"[billing] Conversation quota exceeded for tenant {tenant_db_id}")
            return schemas.ChatReplyResponse(
                conversation_id="",
                message_id="",
                role=MessageRole.assistant,
                content=_BILLING_LIMIT_MESSAGE,
            )

    # ── 3. Billing gate — token quota ────────────────────────────────────────
    allowed, _, _, _ = await can_continue_conversation(
        db, tenant_id=tenant_db_id, current_tokens_used=0
    )
    if not allowed:
        logger.info(f"[billing] Token quota exceeded for tenant {tenant_db_id}")
        return schemas.ChatReplyResponse(
            conversation_id="",
            message_id="",
            role=MessageRole.assistant,
            content=_BILLING_LIMIT_MESSAGE,
        )

    # ── 4. Campaign URL matching (new conversations only) ──────────────────
    # Load all active campaigns for this chatbot and collect EVERY campaign
    # whose url_patterns match the visitor's page — not just the first one.
    # This happens BEFORE creating the conversation so all campaign IDs are
    # written to the junction table at conversation start.
    matched_campaigns: list = []
    if is_new_request:
        try:
            active_campaigns = await campaign_repo.get_active_campaigns_for_chatbot(
                db, chatbot_config_id=chatbot.id
            )
            matched_campaigns = campaign_repo.match_campaigns_for_url(
                active_campaigns, page_url=payload.page_url
            )
            if matched_campaigns:
                logger.info(
                    "[campaign] Matched %d campaign(s) %s for page_url=%r tenant=%d",
                    len(matched_campaigns),
                    [c.public_id for c in matched_campaigns],
                    payload.page_url,
                    tenant_db_id,
                )
        except Exception as exc:
            # Never let campaign matching break the chat flow
            logger.warning("[campaign] Campaign matching failed (degrading gracefully): %s", exc)

    # ── 5. Resolve or create conversation ──────────────────────────────────
    # campaign_id on the conversation is set to the first (highest-priority)
    # matched campaign for backward compatibility with existing queries.
    # The full list is written to conversation_campaigns below.
    conversation, is_new = await repo.get_or_create_conversation(
        db,
        conversation_public_id=payload.conversation_id,
        tenant_id=tenant_str,
        chatbot_config_id=chatbot.id,
        campaign_id=matched_campaigns[0].id if matched_campaigns else None,
        page_url=payload.page_url,
    )

    # Link ALL matched campaigns to the new conversation in the junction table.
    if is_new and matched_campaigns:
        try:
            await repo.link_campaigns_to_conversation(
                db,
                conversation_id=conversation.id,
                campaign_ids=[c.id for c in matched_campaigns],
            )
        except Exception as exc:
            logger.warning("[campaign] Failed to link campaigns to conversation (degrading gracefully): %s", exc)

    # ── 6. Returning visitor detection ─────────────────────────────────────
    returning_visitor_prompt_data = None
    identity_value, identity_type, identity_valid = extract_and_validate_identity(
        payload.message
    )
    if identity_valid and not conversation.identity_hash:
        identity_hash = hash_identity(identity_value)
        previous_sessions = await repo.get_previous_sessions_by_identity(
            db,
            identity_hash=identity_hash,
            exclude_conversation_id=conversation.id,
            tenant_id=tenant_str,
        )
        if previous_sessions:
            logger.info(
                f"[chat] Returning visitor — {len(previous_sessions)} previous session(s)"
            )
            returning_visitor_prompt_data = get_returning_visitor_prompt(previous_sessions)

    # ── 6.5. Load conversation history early (needed for RAG query synthesis) ──
    # For new conversations history is empty; we still set the variable here so
    # step 9 can reuse it without a second DB round-trip.
    conversation_history: list = []
    if not is_new:
        try:
            conversation_history = await repo.get_conversation_history(
                db,
                conversation__id=conversation.id,
                limit=_CHAT_HISTORY_LIMIT,
            )
        except Exception as exc:
            logger.warning("[chat] Failed to load conversation history early: %s", exc)

    # ── 7. RAG retrieval ────────────────────────────────────────────────────
    # Build a synthesized query from all prior user turns + the current message
    # so the embedding captures full intent (rooms, budget, suburb, etc.) rather
    # than only the latest short follow-up like "show me what's available".
    _prior_user_msgs = [
        msg.content for msg in conversation_history
        if msg.role == MessageRole.user
    ][-_RAG_QUERY_USER_TURNS:]  # cap to last N turns so embedding stays bounded
    rag_query = " ".join(_prior_user_msgs + [payload.message]) if _prior_user_msgs else payload.message
    logger.info("[rag] synthesized query from %d prior user turn(s): %r", len(_prior_user_msgs), rag_query[:120])

    rag_chunk_texts: list[str] = []
    if chatbot.rag_enabled:
        try:
            # Use a SAVEPOINT so that any SQL failure inside rag_search is
            # rolled back atomically — without poisoning the outer transaction.
            # Without this, a failed SELECT (e.g. missing column) would put
            # the entire session into InFailedSQLTransactionError state and
            # the subsequent message INSERT would also fail.
            async with db.begin_nested():
                rag_response = await chatbot_service.rag_search(
                    db,
                    tenant_id=tenant_db_id,
                    chatbot_public_id=chatbot.public_id,
                    query=rag_query,
                    top_k=_RAG_TOP_K,
                    listing_top_k=_LISTING_TOP_K,
                )
            rag_chunk_texts = [c.content for c in rag_response.chunks if c.content]
            logger.info(f"[rag] Retrieved {len(rag_chunk_texts)} chunks for tenant {tenant_db_id}")
        except Exception as exc:
            logger.warning(f"[rag] RAG retrieval failed (degrading gracefully): {exc}")

    # ── 8. Assemble system prompt (3-layer) ────────────────────────────────
    #
    #  LAYER 1  static_base       — pre-built personality + company profile (on chatbot)
    #  LAYER 2  campaign_overlay  — campaign goal/tone/CTA (NEW, matched per page URL)
    #  LAYER 3  dynamic_suffix    — RAG chunks + time awareness + returning visitor
    #
    # The campaign overlay sits between the fixed persona and the live knowledge
    # so the LLM has a "mission brief" that scopes how it uses the RAG data.

    static_base = chatbot.system_prompt_template or ""

    # For existing conversations: load campaigns from the junction table.
    # Fall back to the legacy campaign_id column for old conversations that
    # pre-date the junction table.
    if not is_new_request and not matched_campaigns:
        try:
            matched_campaigns = await repo.get_campaigns_for_conversation(
                db, conversation_id=conversation.id
            )
            if not matched_campaigns and conversation.campaign_id:
                # Legacy fallback — conversation was created before junction table
                from app.modules.campaigns.models import Campaign
                from sqlalchemy import select as sa_select
                result = await db.execute(
                    sa_select(Campaign).where(Campaign.id == conversation.campaign_id)
                )
                legacy = result.scalar_one_or_none()
                if legacy:
                    matched_campaigns = [legacy]
        except Exception as exc:
            logger.warning("[campaign] Failed to load campaigns for existing conversation: %s", exc)

    campaign_overlay_block = ""
    if matched_campaigns:
        campaign_overlay_block = build_campaign_overlays_block(matched_campaigns)

    time_aware_data = get_time_awareness_prompt(payload.user_local_timestamp)

    dynamic_suffix = build_dynamic_context(
        rag_chunks=rag_chunk_texts if rag_chunk_texts else None,
        time_prompt=time_aware_data,
        returning_visitor_prompt=returning_visitor_prompt_data,
    )

    prompt_parts = [static_base]
    if campaign_overlay_block:
        prompt_parts.append(campaign_overlay_block)
    if dynamic_suffix:
        prompt_parts.append(dynamic_suffix)
    system_prompt = "\n\n".join(p for p in prompt_parts if p)

    # ── 9. Build LLM message context ────────────────────────────────────────
    # Show the campaign welcome_message only when the campaign targets a specific
    # URL (url_patterns non-empty) or covers the whole website (is_default=True).
    # A campaign with neither should not override the bot-level welcome message.
    _campaign_welcome: str | None = None
    if matched_campaigns:
        _first = matched_campaigns[0]
        if (_first.url_patterns or _first.is_default) and _first.welcome_message:
            _campaign_welcome = _first.welcome_message

    welcome_message = (
        _campaign_welcome
        or chatbot.welcome_message
        or "Hi, I am ARIA. What can I help you with today?"
    )

    llm_messages: list[dict] = []

    if not is_new:
        # Reuse history loaded in step 6.5 — no second DB round-trip needed
        llm_messages = [
            {"role": msg.role.value, "content": msg.content}
            for msg in conversation_history
        ]
    else:
        llm_messages.append({"role": "assistant", "content": welcome_message})

    # Inject returning-visitor reminder immediately before current message
    if returning_visitor_prompt_data:
        llm_messages.append({
            "role": "user",
            "content": (
                "SYSTEM REMINDER: Before replying to my next message, "
                "acknowledge that I have visited before and give a natural recap "
                "of our previous conversation. Context: "
                + json.dumps(returning_visitor_prompt_data)
            ),
        })
        llm_messages.append({
            "role": "assistant",
            "content": (
                "Understood. I will acknowledge your return and naturally recap "
                "our previous conversation before responding to your message."
            ),
        })

    llm_messages.append({"role": "user", "content": payload.message})

    # ── 10. Call LLM (with token usage tracking) ────────────────────────────
    try:
        t0 = datetime.now()
        assistant_content, tokens_used = await openai_service.openai_call_with_usage(
            llm_messages,
            system_prompt,
        )
        response_ms = int((datetime.now() - t0).total_seconds() * 1000)
    except Exception as exc:
        logger.exception("LLM call failed: %s", exc)
        assistant_content = "Sorry, I could not process your request right now."
        tokens_used = 0
        response_ms = None

    # ── 11. Prepare messages for batch insert ───────────────────────────────
    messages_to_insert: list[Message] = []

    if is_new:
        messages_to_insert.append(
            Message(
                conversation_id=conversation.id,
                role=MessageRole.assistant,
                content=welcome_message,
            )
        )

    messages_to_insert.extend([
        Message(
            conversation_id=conversation.id,
            role=MessageRole.user,
            content=payload.message,
        ),
        Message(
            conversation_id=conversation.id,
            role=MessageRole.assistant,
            content=assistant_content,
            tokens_used=tokens_used,
            model_used=openai_service.OPENAI_CALL_PARAMS.get("model"),
            response_ms=response_ms,
        ),
    ])

    # ── 12. Persist messages ────────────────────────────────────────────────
    persisted = await repo.add_messages(db, messages=messages_to_insert)
    assistant_msg = persisted[-1]

    # ── 13. Update conversation counters ────────────────────────────────────
    await repo.update_conversation_activity(
        conversation,
        message_increment=len(messages_to_insert),
        token_increment=tokens_used,
    )

    # ── 14. Commit ──────────────────────────────────────────────────────────
    await db.commit()

    # ── 15. Increment billing usage records (post-commit, non-blocking) ─────
    # Token increment — always
    if tokens_used > 0:
        try:
            await increment_and_check(
                db,
                tenant_id=tenant_db_id,
                metric=UsageMetric.TOKENS_USED,
                metric_key="max_tokens_per_month",
                amount=tokens_used,
                default_limit=_DEFAULT_MAX_TOKENS,
            )
        except Exception:
            logger.warning(f"[billing] Failed to increment token usage for tenant {tenant_db_id}")

    # Conversation increment — only for new sessions
    if is_new:
        try:
            await increment_and_check(
                db,
                tenant_id=tenant_db_id,
                metric=UsageMetric.CONVERSATIONS,
                metric_key="max_conversations_per_month",
                amount=1,
                default_limit=_DEFAULT_MAX_CONVERSATIONS,
            )
        except Exception:
            logger.warning(f"[billing] Failed to increment conversation usage for tenant {tenant_db_id}")

    await db.commit()

    # ── 16. Return response ─────────────────────────────────────────────────
    return schemas.ChatReplyResponse(
        conversation_id=conversation.public_id,
        message_id=assistant_msg.public_id,
        role=MessageRole.assistant,
        content=assistant_content,
    )


# ---------------------------------------------------------------------------
# 2. Chat — Admin console (stateless, no DB interaction)
# ---------------------------------------------------------------------------

async def admin_console_chat(
    db: AsyncSession,
    *,
    payload: schemas.AdminConsoleChatCreateRequest,
) -> schemas.AdminConsoleChatReplyResponse:
    """
    Stateless chat for the admin console.
    Resolves the chatbot via iframe_token, uses its own system prompt,
    and returns the reply with the rag_enabled flag.
    Only reads from the database (chatbot lookup). Nothing is written.
    """
    # ── 1. Resolve chatbot via iframe_token ─────────────────────────────────
    chatbot = await chatbot_repo.get_chatbot_by_iframe_token(
        db, iframe_token=payload.iframe_token
    )
    if chatbot is None:
        raise ValueError("Chatbot not found. Check the iframe_token.")

    if chatbot.status != "active":
        return schemas.AdminConsoleChatReplyResponse(
            role=MessageRole.assistant,
            content=_BILLING_LIMIT_MESSAGE,
            rag_enabled=False,
        )

    # ── 2. Network (RAG) enabled flag — read once, returned to frontend ──────
    rag_enabled: bool = chatbot.rag_enabled

    # ── 3. Build system prompt from the chatbot's own template ───────────────
    system_prompt = chatbot.system_prompt_template or ""
    time_aware = get_time_awareness_prompt(payload.user_local_timestamp)
    system_prompt += "\n\nTime awareness: " + json.dumps(time_aware)

    # ── 4. Build LLM messages from full history ──────────────────────────────
    llm_messages: list[dict] = [
        {"role": msg.role.value, "content": msg.content}
        for msg in payload.messages
    ]

    # ── 5. Call LLM ──────────────────────────────────────────────────────────
    try:
        assistant_content = await openai_service.openai_call_conversation(
            llm_messages,
            system_prompt,
        )
    except Exception as exc:
        logger.exception("LLM call failed in admin console chat: %s", exc)
        assistant_content = "Sorry, I could not process your request right now."

    return schemas.AdminConsoleChatReplyResponse(
        role=MessageRole.assistant,
        content=assistant_content,
        rag_enabled=rag_enabled,
    )



# ---------------------------------------------------------------------------
# 4. Conversation list  (keyset paginated)
# ---------------------------------------------------------------------------

async def list_conversations(
    db: AsyncSession,
    *,
    payload: schemas.ConversationListRequest,
    tenant_id: str,
) -> schemas.PaginatedResponse[schemas.ConversationSummaryResponse]:
    logger.debug("[chat] list_conversations tenant=%s page_size=%d cursor=%s", tenant_id, payload.page_size, payload.cursor)
    conversations, next_cursor, total = await repo.get_conversations(
        db,
        tenant_id=tenant_id,
        page_size=payload.page_size,
        cursor=payload.cursor,
        status=payload.status,
    )

    items = [
        schemas.ConversationSummaryResponse(
            id=conv.public_id,
            status=conv.status,
            is_lead=conv.is_lead,
            total_messages=conv.total_messages,
            total_tokens_used=conv.total_tokens_used,
            created_at=conv.created_at,
            last_activity_at=conv.last_activity_at,
        )
        for conv in conversations
    ]

    return schemas.PaginatedResponse(
        items=items,
        meta=schemas.PaginatedMeta(
            total=total,
            page_size=payload.page_size,
            next_cursor=next_cursor,
            has_next=next_cursor is not None,
        ),
    )


# ---------------------------------------------------------------------------
# 4. Conversation detail
# ---------------------------------------------------------------------------

async def get_conversation_detail(
    db: AsyncSession,
    *,
    conversation_public_id: str,
    tenant_id: str,
) -> schemas.ConversationDetailResponse:
    conversation = await repo.get_conversation_detail(
        db,
        public_id=conversation_public_id,
        tenant_id=tenant_id,
    )
    if conversation is None:
        raise ValueError(f"Conversation '{conversation_public_id}' not found.")

    messages = [
        schemas.MessageResponse(
            id=msg.public_id,
            role=msg.role,
            content=msg.content,
            tokens_used=msg.tokens_used,
            model_used=msg.model_used,
            response_ms=msg.response_ms,
            created_at=msg.created_at,
        )
        for msg in conversation.messages
    ]

    return schemas.ConversationDetailResponse(
        id=conversation.public_id,
        status=conversation.status,
        is_lead=conversation.is_lead,
        total_messages=conversation.total_messages,
        total_tokens_used=conversation.total_tokens_used,
        created_at=conversation.created_at,
        last_activity_at=conversation.last_activity_at,
        messages=messages,
    )


# ---------------------------------------------------------------------------
# 5. Conversation completion
# ---------------------------------------------------------------------------

async def complete_conversation(
    db: AsyncSession,
    *,
    payload: schemas.ChatCompleteRequest,
) -> schemas.ChatCompleteResponse:
    logger.info("[chat] complete_conversation conversation_id=%s iframe_token=%s", payload.conversation_id, payload.iframe_token)
    # Resolve chatbot to scope the conversation lookup
    chatbot = await chatbot_repo.get_chatbot_by_iframe_token(
        db, iframe_token=payload.iframe_token
    )
    if chatbot is None:
        logger.warning("[chat] complete_conversation chatbot not found iframe_token=%s", payload.iframe_token)
        raise ValueError("Chatbot not found.")

    tenant_str = str(chatbot.tenant_id)

    conversation = await repo.get_conversation_by_public_id(
        db,
        conversation_public_id=payload.conversation_id,
        tenant_id=tenant_str,
    )
    if not conversation:
        raise ValueError(f"Conversation '{payload.conversation_id}' not found.")
    if conversation.status == ConversationStatus.closed:
        raise ValueError("Conversation is already closed.")

    await repo.update_conversation_status(
        db,
        conversation__id=conversation.id,
        tenant_id=tenant_str,
        status=ConversationStatus.closed.value,
    )
    await db.commit()

    celery_task = background_tasks.chat_completion_task.delay(
        conversation.id, tenant_str
    )
    logger.info(f"[chat] Completion task enqueued: {celery_task.id}")

    return schemas.ChatCompleteResponse(
        task_id=celery_task.id,
        status=celery_task.status,
    )
