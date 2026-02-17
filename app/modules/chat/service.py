# app/modules/chat/service.py

from uuid import UUID
from uuid6 import uuid7
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from . import repository
from .schemas import (
    ChatCreateRequest,
    ChatConversationResponse,
    ChatMessageResponse,
    ChatInsightResponse,
)


# ----------------------------
# Create or Append Chat
# ----------------------------

async def create_chat_message(
    db: AsyncSession,
    payload: ChatCreateRequest,
) -> ChatMessageResponse:

    # Does conversation exist?
    conversation = await repository.get_conversation_by_user_and_business(
        db=db,
        user_id=payload.user_id,
        business_id=payload.business_id,
    )

    if not conversation:
        chat_id = uuid7()
        conversation = await repository.create_conversation(
            db=db,
            chat_id=chat_id,
            user_id=payload.user_id,
            business_id=payload.business_id,
        )
    else:
        chat_id = conversation.chat_id

    message = await repository.create_message(
        db=db,
        chat_id=chat_id,
        user_id=payload.user_id,
        message=payload.message,
    )

    return ChatMessageResponse.model_validate(message)


async def get_conversation(
    db: AsyncSession,
    chat_id: UUID,
) -> ChatConversationResponse:

    conversation = await repository.get_conversation_by_id(
        db=db,
        chat_id=chat_id,
    )

    if not conversation:
        raise NotFoundException("Conversation not found")

    messages = await repository.get_messages_by_chat_id(
        db=db,
        chat_id=chat_id,
    )

    return ChatConversationResponse(
        chat_id=conversation.chat_id,
        business_id=conversation.business_id,
        messages=[
            ChatMessageResponse.model_validate(msg)
            for msg in messages
        ],
    )


# async def get_chat_insight(
#     db: AsyncSession,
#     chat_id: UUID,
# ) -> ChatInsightResponse:

#     stats = await repository.get_chat_statistics(
#         db=db,
#         chat_id=chat_id,
#     )

#     if not stats:
#         raise NotFoundException("Chat not found")

#     return ChatInsightResponse(
#         chat_id=chat_id,
#         total_messages=stats["total_messages"],
#         last_message_at=stats["last_message_at"],
#     )
