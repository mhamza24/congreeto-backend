# app/modules/chat/schemas.py

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class ChatCreateRequest(BaseModel):
    user_id: UUID
    message: str
    business_id: UUID


class ChatMessageResponse(BaseModel):
    id: UUID
    chat_id: UUID
    user_id: UUID
    message: str
    created_at: datetime


class ChatConversationResponse(BaseModel):
    chat_id: UUID
    business_id: UUID
    messages: List[ChatMessageResponse]


class ChatInsightResponse(BaseModel):
    chat_id: UUID
    total_messages: int
    last_message_at: Optional[datetime]
