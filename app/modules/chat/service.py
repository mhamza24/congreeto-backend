"""
service.py — Business logic layer for the chat module.

Responsibilities
────────────────
- Orchestrate repository calls (never raw SQL here).
- Build LLM message context from conversation history.
- Map ORM objects → response schemas (the "anti-corruption" layer).
- Own the DB transaction boundary (commit lives here, not in the router).

The service receives and returns public_ids only — internal PKs stay inside
the repository.
"""

from __future__ import annotations
from fastapi import status
import json
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import http_exception_handler
from app.modules.open_ai import service as openai_service
from app.modules.chat import tasks as background_tasks
from app.utils.email_extractor import extract_and_validate_identity
from app.utils.hashing_utils import hash_identity
from app.utils.system_prompt_aria import aria_veloce_website_guide
from app.utils.system_prompt_aria_veloce import aria_veloce_brand_representative
from app.utils.system_prompt_portfolio import veloce_portfolio
from app.utils.system_prompt_time_awareness import get_time_awareness_prompt
from app.modules.chat.models import ConversationStatus, Message
from app.utils.system_prompt_previous_sessions import get_returning_visitor_prompt

from . import repository as repo
from . import schemas
from .models import MessageRole

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Chat — create or continue
# ---------------------------------------------------------------------------

async def create_or_continue_chat(
    db: AsyncSession,
    *,
    payload: schemas.ChatCreateRequest,
) -> schemas.ChatReplyResponse:

    # ── 1. Resolve conversation ─────────────────────────────────────────────
    conversation, is_new = await repo.get_or_create_conversation(
        db,
        conversation_public_id=payload.conversation_id,
        tenant_id=payload.tenant_id,
    )

    # ── 2. Previous session recall ──────────────────────────────────────────
    # Only on first message of a new conversation — never mid-chat.
    # Purely read — no DB writes here.
    returning_visitor_prompt = None

    identity_value, identity_type, identity_valid = extract_and_validate_identity(
            payload.message
        )
    print("identity_type", identity_type)
    logger.info(f"[chat] identity_value={identity_value} type={identity_type} valid={identity_valid}")

    if identity_valid:
            identity_hash = hash_identity(identity_value)
            print("identity_hash", identity_hash)
            previous_sessions = await repo.get_previous_sessions_by_identity(
                db,
                identity_hash=identity_hash,
                exclude_conversation_id=conversation.id,
                tenant_id=payload.tenant_id,
            )

            if previous_sessions:
                print(
                    f"Previous sessions found for identity hash {identity_hash}: {[s.public_id for s in previous_sessions]}")
                logger.info(f"[chat] Returning visitor — {len(previous_sessions)} previous session(s) found")
                returning_visitor_prompt = get_returning_visitor_prompt(previous_sessions)

    # ── 3. Build system prompt ──────────────────────────────────────────────
    time_aware_system_prompt = get_time_awareness_prompt(
        payload.user_local_timestamp
    )

    if payload.chatbot_identity == schemas.ChatbotIdentityEnum.website:
        system_prompt = json.dumps(aria_veloce_website_guide)
    else:
        system_prompt = json.dumps(aria_veloce_brand_representative)
        system_prompt += "\n\nCompany portfolio: " + json.dumps(veloce_portfolio)

    system_prompt += "\n\nTime awareness: " + json.dumps(time_aware_system_prompt)

    if returning_visitor_prompt:
        system_prompt += "\n\nReturning visitor context: " + json.dumps(returning_visitor_prompt)

    # ── 4. Build LLM context ────────────────────────────────────────────────
    llm_messages: list[dict] = []

    if not is_new:
        history = await repo.get_conversation_history(
            db,
            conversation__id=conversation.id,
            limit=50,
        )
        llm_messages = [
            {"role": msg.role.value, "content": msg.content}
            for msg in history
        ]
    else:
        greeting = "Hi, I'm Aria your guide to everything Veloce. What can I help with?"
        llm_messages.append({"role": "assistant", "content": greeting})

    llm_messages.append({"role": "user", "content": payload.message})

    # ── 5. Call LLM ─────────────────────────────────────────────────────────
    try:
        t0 = datetime.now()
        assistant_content = await openai_service.openai_call_conversation(
            llm_messages,
            system_prompt,
        )
        response_ms = int((datetime.now() - t0).total_seconds() * 1000)
    except Exception as exc:
        logger.exception("LLM call failed: %s", exc)
        assistant_content = "Sorry, I could not process your request right now."
        response_ms = None

    # ── 6. Prepare messages for persistence ─────────────────────────────────
    messages_to_insert = []

    if is_new:
        messages_to_insert.append(
            Message(
                conversation_id=conversation.id,
                role=MessageRole.assistant,
                content="Hi, I'm Aria your guide to everything Veloce. What can I help with?",
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
            response_ms=response_ms,
        ),
    ])

    # ── 7. Persist messages in one batch ─────────────────────────────────────
    persisted_messages = await repo.add_messages(db, messages=messages_to_insert)
    assistant_msg = persisted_messages[-1]

    # ── 8. Update counters ────────────────────────────────────────────────────
    await repo.update_conversation_activity(
        conversation,
        message_increment=len(messages_to_insert),
    )

    # ── 9. Commit ────────────────────────────────────────────────────────────
    await db.commit()

    # ── 10. Return response ───────────────────────────────────────────────────
    return schemas.ChatReplyResponse(
        conversation_id=conversation.public_id,
        message_id=assistant_msg.public_id,
        role=MessageRole.assistant,
        content=assistant_content,
    )


# ---------------------------------------------------------------------------
# 2. Conversation list (keyset paginated)
# ---------------------------------------------------------------------------

async def list_conversations(
    db: AsyncSession,
    *,
    payload: schemas.ConversationListRequest,
    tenant_id: str,
) -> schemas.PaginatedResponse[schemas.ConversationSummaryResponse]:
    """
    Return a page of conversations (no messages — list view is lightweight).

    Uses keyset pagination — see repository.get_conversations for details.
    N+1 cannot occur here because messages are never loaded.
    """
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
# 3. Conversation detail (with messages, eager loaded)
# ---------------------------------------------------------------------------

async def get_conversation_detail(
    db: AsyncSession,
    *,
    conversation_public_id: str,
    tenant_id: str,
) -> schemas.ConversationDetailResponse:
    """
    Fetch a single conversation with all its messages.

    Exactly 2 SQL queries regardless of message count (selectinload batch).
    No N+1.
    """
    conversation = await repo.get_conversation_detail(
        db,
        public_id=conversation_public_id,
        tenant_id=tenant_id,
    )

    if conversation is None:
        raise ValueError(
            f"Conversation '{conversation_public_id}' not found."
        )

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
        for msg in conversation.messages   # already loaded — no extra query
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
# 4. Conversation completion (trigger background analysis task)
# ---------------------------------------------------------------------------

async def complete_conversation(
    db: AsyncSession,
    *,
    payload: schemas.ChatCompleteRequest,

) -> schemas.ChatCompleteResponse:
    print(payload)
    if payload.tenant_id not in ("veloce", "veloce_website"):
        raise ValueError(f"Tenant with ID {payload.tenant_id} not found.")

    conversation_exists = await repo.get_conversation_by_public_id(
        db,
        conversation_public_id=payload.conversation_id,
        tenant_id=payload.tenant_id,
    )
    logger.info(conversation_exists)

    if not conversation_exists:
        raise ValueError(
            f"Conversation with ID {payload.conversation_id} not found.")
    if conversation_exists.status == ConversationStatus.closed:
        raise ValueError("Conversation is already closed")

    await repo.update_conversation_status(
        db,
        conversation__id=conversation_exists.id,
        tenant_id=payload.tenant_id,
        status=schemas.ConversationStatus.closed.value
    )
    await db.commit()
    celery_task = background_tasks.chat_completion_task.delay(
        conversation_exists.id, payload.tenant_id)

    logger.info(
        f"Task enqueued: {celery_task.id}, initial status: {celery_task.status}")
    return schemas.ChatCompleteResponse(
        task_id=celery_task.id,
        status=celery_task.status

    )
