from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from typing import Tuple, Optional, List

from .models import Conversation, Messages, MessageRole, ConversationStatus


async def get_or_create_conversation(
    db: AsyncSession,
    chat_id: Optional[str],
    tenant_id: str
) -> Tuple[Conversation, bool]:

    if chat_id:
        result = await db.execute(
            select(Conversation).where(Conversation.id == chat_id)
        )
        conversation = result.scalar_one_or_none()

        if conversation:
            return conversation, False

    # Create new conversation
    conversation = Conversation(
        id=chat_id if chat_id else None,
        tenant_id=tenant_id,
        status=ConversationStatus.in_progress,
    )
    db.add(conversation)
    await db.flush()

    return conversation, True


async def add_message(
    db: AsyncSession,
    conversation_id: str,
    role: MessageRole,
    content: str,
    tokens_used: int | None = None,
    model_used: str | None = None,
    response_ms: int | None = None,
) -> Messages:

    message = Messages(
        conversation_id=conversation_id,
        role=role,
        content=content,
        tokens_used=tokens_used,
        model_used=model_used,
        response_ms=response_ms,
    )
    db.add(message)
    await db.flush()
    return message


async def get_messages(
    db: AsyncSession,
    conversation_id: str
) -> List[Messages]:

    result = await db.execute(
        select(Messages)
        .where(Messages.conversation_id == conversation_id)
        .order_by(Messages.created_at)
    )
    return result.scalars().all()


async def update_conversation_activity(
    conversation: Conversation,
    token_increment: int = 0,
    message_increment: int = 0,
):
    conversation.total_tokens_used += token_increment
    conversation.total_messages += message_increment
    conversation.last_activity_at = datetime.now(timezone.utc)
