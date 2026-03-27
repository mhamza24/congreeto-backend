# app/modules/chat/schemas.py
from fastapi import Query
from pydantic import BaseModel, Field
from typing import Optional, List, Union, TypeVar, Generic
from datetime import datetime
from enum import Enum
from uuid import UUID
from app.modules.chat.models import ConversationStatus, MessageRole

DataT = TypeVar("DataT")

# ---------------------------------------------------------------------------
# Shared / primitives
# ---------------------------------------------------------------------------

class RoleEnum(str, Enum):
    system = "system"
    user = "user"
    assistant = "assistant"


class ChatMessage(BaseModel):
    role: RoleEnum
    content: str


class ChatbotIdentityEnum(str, Enum):
    website = "website"
    veloce_demo = "veloce_demo"
    leo_odysseynleo="leo_odysseynleo"


class ChatMessagePair(BaseModel):
    user: str
    assistant: str
    
class AdminConsoleMessage(BaseModel):
    role: MessageRole
    content: str = Field(..., min_length=1, max_length=32_000)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class ChatCreateRequest(BaseModel):
    """
    Create or continue a conversation.

    - Omit `conversation_id` to start a new conversation.
    - Pass an existing `conversation_id` (public_id) to continue one.
    """
    conversation_id: Optional[str] = Field(
        default=None,
        description="Public conversation ID (uuid7). Omit to start a new conversation.",
    )
    message: str = Field(..., min_length=1, max_length=32_000)
    chatbot_identity: ChatbotIdentityEnum = Field(
        default=ChatbotIdentityEnum.veloce_demo.value,
        description="Main Veloce website or Veloce as a client, for system prompt",
    )
    tenant_id: str = Field(min_length=1, max_length=100,
                           default="veloce",
                           description="Tenant ID for multi-tenancy (extracted from auth in real implementation).")
    user_local_timestamp: Optional[datetime] = Field(
        default=None, description="User's local timestamp for time-aware system prompts (optional, ISO format)")



class AdminConsoleChatCreateRequest(BaseModel):
    """
    Stateless admin console chat — no DB persistence.
    Pass the full conversation history (including the latest user message) on every call.
    """
    messages: list[AdminConsoleMessage] = Field(
        ...,
        min_length=1,
        description="Full conversation history with roles. Latest user message must be last.",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Optional tenant ID for custom personalization.",
    )
    user_local_timestamp: Optional[datetime] = Field(
        default=None,
        description="User's local timestamp for time-aware system prompts (ISO format).",
    )


class ChatCompleteRequest(BaseModel):
    """
    Complete a conversation.

    - Omit `conversation_id` to start a complete conversation.
    - Pass an existing `conversation_id` (public_id) to continue one.
    """
    conversation_id: str = Field(
        default=None,
        description="Public conversation ID (uuid7). Omit to complete a  conversation.",
    )
    tenant_id: str = Field(min_length=1, max_length=100,
                           default="veloce",
                           description="Tenant ID for multi-tenancy (extracted from auth in real implementation).")




class ConversationListRequest(BaseModel):
    """
    Keyset (cursor) pagination parameters for listing conversations.

    Cursor encodes `created_at` + `public_id` of the last seen row so the
    database never needs OFFSET scans — O(log n) regardless of page depth.
    Use `page_size` + `cursor` returned by the previous response to paginate.
    """
    page_size: int = Field(default=20, ge=1, le=100)
    cursor: Optional[str] = Field(
        default=None,
        description=(
            "Opaque cursor from the previous response's `next_cursor` field. "
            "Omit for the first page."
        ),
    )
    status: Optional[ConversationStatus] = Field(
        default=None,
        description="Filter by conversation status.",
    )


# ---------------------------------------------------------------------------
# Response schemas — messages
# ---------------------------------------------------------------------------

class MessageResponse(BaseModel):
    id: str = Field(description="Public message ID (uuid7).")
    role: MessageRole
    content: str
    tokens_used: Optional[int]
    model_used: Optional[str]
    response_ms: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Response schemas — conversations (list view, no messages)
# ---------------------------------------------------------------------------

class ConversationSummaryResponse(BaseModel):
    """
    Lightweight conversation row — returned by the list endpoint.
    Does NOT include messages (avoids N+1 and keeps payload small).
    """
    id: str = Field(description="Public conversation ID (uuid7).")
    status: ConversationStatus
    is_lead: bool
    total_messages: int
    total_tokens_used: int
    created_at: datetime
    last_activity_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Response schemas — conversations (detail view, with messages)
# ---------------------------------------------------------------------------

class ConversationDetailResponse(BaseModel):
    """
    Full conversation with all messages — returned by the detail endpoint.
    Messages are eagerly loaded in a single query (no N+1).
    """
    id: str = Field(description="Public conversation ID (uuid7).")
    status: ConversationStatus
    is_lead: bool
    total_messages: int
    total_tokens_used: int
    created_at: datetime
    last_activity_at: datetime
    messages: List[MessageResponse]
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Response schemas — chat endpoint
# ---------------------------------------------------------------------------

class ChatReplyResponse(BaseModel):
    conversation_id: str = Field(description="Public conversation ID (uuid7).")
    message_id: str = Field(description="Public message ID (uuid7).")
    role: MessageRole
    content: str


class AdminConsoleChatReplyResponse(BaseModel):
    role: MessageRole
    content: str


class ChatCompleteResponse(BaseModel):
    # message: str = Field(
    #     description="Chat marks the conversation as complete, initiate Ai insights pipeline.")
    task_id: str = Field(
        description="unique identifier chat completion task for tracking in background task manager like Celery")
    status: str = Field(
        description="background task status: pending, completed, failed")




# ---------------------------------------------------------------------------
# Pagination envelope
# ---------------------------------------------------------------------------

class PaginatedMeta(BaseModel):
    total: int
    page_size: int
    next_cursor: Optional[str] = Field(
        default=None,
        description=(
            "Pass this as `cursor` in the next request to fetch the next page. "
            "Null means you have reached the last page."
        ),
    )
    has_next: bool


class PaginatedResponse(BaseModel, Generic[DataT]):
    items: List[DataT]
    meta: PaginatedMeta
