# app/modules/chat/schemas.py

from pydantic import BaseModel, Field
from typing import Optional, List, Union
from datetime import datetime
from enum import Enum
from uuid import UUID


class RoleEnum(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    role: RoleEnum
    content: str


class ChatMessagePair(BaseModel):
    user: str
    assistant: str


class TempChatCreateRequest(BaseModel):
    chat_id: Union[UUID, None] = None
    message: Union[
        str,
        ChatMessagePair,
        ChatMessage,
        List[Union[str, ChatMessagePair, ChatMessage]]
    ]


class ChatMessageResponse(BaseModel):
    chat_id: UUID
    message_id: UUID
    message: ChatMessage
