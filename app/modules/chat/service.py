# app/modules/chat/service.py

from uuid import UUID
from uuid6 import uuid7
from typing import List, Union, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from . import repository
from .import schemas as chat_schemas
from app.utils.chat_helper import normalize_conversation
from app.modules.open_ai import service as open_ai_service
import logging

logger = logging.getLogger(__name__)
# Placeholder for "database"
CONVERSATIONS = {}  # {chat_id: list of messages}

system_prompt = "Act as a real estate agent."


async def create_or_continue_chat(payload: chat_schemas.TempChatCreateRequest) -> chat_schemas.ChatMessageResponse:
    chat_id = payload.chat_id or uuid7()
    # normalize user messages
    normalized_messages = normalize_conversation(payload.message)

    # prepend system prompt
    normalized_messages.insert(
        0, {"role": chat_schemas.RoleEnum.SYSTEM.value, "content": system_prompt})

    # call OpenAI LLM
    try:
        assistant_content = await open_ai_service.call_openai(normalized_messages, system_prompt)
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        assistant_content = "Sorry, I could not process your request."

    # append assistant response
    normalized_messages.append(
        {"role": chat_schemas.RoleEnum.ASSISTANT.value, "content": assistant_content})

    # store messages in memory
    if chat_id not in CONVERSATIONS:
        CONVERSATIONS[chat_id] = []

    response_messages = []
    for msg in normalized_messages:
        message_id = uuid7()
        msg_record = {"message_id": message_id,
                      "chat_id": chat_id, "message": msg}
        CONVERSATIONS[chat_id].append(msg_record)

        response_messages.append(chat_schemas.ChatMessageResponse(
            chat_id=chat_id,
            message_id=message_id,
            message=chat_schemas.ChatMessage(
                role=msg["role"], content=msg["content"])
        ))

    return response_messages[-1]

# ----------------------------
# Create or Append Chat
# ----------------------------

# async def create_chat_message(
#     db: AsyncSession,
#     payload: ChatCreateRequest,
# ) -> ChatMessageResponse:

#     # Does conversation exist?
#     conversation = await repository.get_conversation_by_user_and_business(
#         db=db,
#         user_id=payload.user_id,
#         business_id=payload.business_id,
#     )

#     if not conversation:
#         chat_id = uuid7()
#         conversation = await repository.create_conversation(
#             db=db,
#             chat_id=chat_id,
#             user_id=payload.user_id,
#             business_id=payload.business_id,
#         )
#     else:
#         chat_id = conversation.chat_id

#     message = await repository.create_message(
#         db=db,
#         chat_id=chat_id,
#         user_id=payload.user_id,
#         message=payload.message,
#     )

#     return ChatMessageResponse.model_validate(message)


# async def get_conversation(
#     db: AsyncSession,
#     chat_id: UUID,
# ) -> ChatConversationResponse:

#     conversation = await repository.get_conversation_by_id(
#         db=db,
#         chat_id=chat_id,
#     )

#     if not conversation:
#         raise NotFoundException("Conversation not found")

#     messages = await repository.get_messages_by_chat_id(
#         db=db,
#         chat_id=chat_id,
#     )

#     return ChatConversationResponse(
#         chat_id=conversation.chat_id,
#         business_id=conversation.business_id,
#         messages=[
#             ChatMessageResponse.model_validate(msg)
#             for msg in messages
#         ],
#     )


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
