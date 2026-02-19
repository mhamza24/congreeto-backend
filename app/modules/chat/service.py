# app/modules/chat/service.py

from datetime import datetime, timezone
from uuid import UUID
from uuid6 import uuid7
from typing import List, Union, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from . import repository as chat_repository
from . import models as chat_models
import json
from app.utils.system_prompt_aria import aria_system_prompt
from .import schemas as chat_schemas
from app.utils.chat_helper import normalize_conversation
from app.modules.open_ai import service as open_ai_service
import logging

logger = logging.getLogger(__name__)



async def create_or_continue_chat(
    payload,
    db: AsyncSession,
    tenant_id: str = "veloce"
):
    print("inside service",payload)

    # 1️⃣ Get or create conversation
    conversation, is_new = await chat_repository.get_or_create_conversation(
        db=db,
        chat_id=payload.chat_id,
        tenant_id=tenant_id
    )
    print("conversation fetched", is_new)
    # 2️⃣ Build LLM context
    system_prompt_json = json.dumps(aria_system_prompt)
    llm_messages = [{"role": "system", "content": system_prompt_json}]

    if not is_new:
        history = await chat_repository.get_messages(db, conversation.id)
        for msg in history:
            llm_messages.append({
                "role": msg.role.value,
                "content": msg.content
            })

    # Add current user message to context
    llm_messages.append({
        "role": "user",
        "content": payload.message
    })
    print("user message added",llm_messages)

    # 3️⃣ Call LLM
    try:
        start_time = datetime.now()
        assistant_content = await open_ai_service.call_openai(
            llm_messages,
            system_prompt_json
        )
        print("ai message", assistant_content)
        response_ms = int((datetime.now() - start_time).total_seconds() * 1000)
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        assistant_content = "Sorry, I could not process your request."
        response_ms = None

    # 4️⃣ Persist messages

    # Store user message
    await chat_repository.add_message(
        db=db,
        conversation_id=conversation.id,
        role=chat_models.MessageRole.user,
        content=payload.message
    )

    # Store assistant message
    assistant_message = await chat_repository.add_message(
        db=db,
        conversation_id=conversation.id,
        role=chat_models.MessageRole.assistant,
        content=assistant_content,
        response_ms=response_ms
    )

    # 5️⃣ Update conversation metadata
    await chat_repository.update_conversation_activity(
        conversation=conversation,
        message_increment=2
    )

    await db.commit()

    return {
        "conversation_id": conversation.id,
        "message_id": assistant_message.id,
        "role": "assistant",
        "content": assistant_content
    }



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
