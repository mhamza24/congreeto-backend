from sqlalchemy import Enum
import uuid
from uuid6 import uuid7
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, Integer, Boolean, DateTime, Enum, ForeignKey, Index
)
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()

# ENUMS


class ConversationStatus(str, enum.Enum):
    in_progress = "in_progress"
    closed = "closed"
    summarized = "summarized"
    emailed = "emailed"
    archived = "archived"

# Helpers


def utcnow():
    return datetime.now(timezone.utc)


def prefixed_uuid(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"

class Conversation(Base):
    __tablename__ = "conversations"

    # Identity
    id = Column(String, primary_key=True,
                default=uuid7())
    Conversation_uuid = Column(String, primary_key=True,
                               default=lambda: prefixed_uuid("conv_"))
    tenant_id = Column(String, nullable=False)
    session_token = Column(String, unique=True, nullable=False,
                           default=lambda: prefixed_uuid("sess_"))
    identity_hash = Column(String, nullable=True)

    # Visitor Info
    visitor_ip_hash = Column(String, nullable=True)
    visitor_ua = Column(String, nullable=True)
    page_url = Column(String, nullable=True)

    # Status & Lifecycle
    status = Column(Enum(ConversationStatus), nullable=False,
                    default=ConversationStatus.in_progress)

    # Lead Capture
    is_lead = Column(Boolean, nullable=False, default=False)
    lead_name = Column(String, nullable=True)
    lead_email = Column(String, nullable=True)
    lead_phone = Column(String, nullable=True)

    # Counters
    total_messages = Column(Integer, nullable=False, default=0)
    total_tokens_used = Column(Integer, nullable=False, default=0)

    # LLM Context
    running_summary = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)

    # Archival
    archive_url = Column(String, nullable=True)

    # Timestamps
    last_activity_at = Column(DateTime(timezone=True),
                              nullable=False, default=utcnow)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True),
                        nullable=False, default=utcnow)

    # Relationship
    messages = relationship("Message", back_populates="conversation",
                            order_by="Message.created_at", lazy="select")

    # Indexes
    __table_args__ = (
        Index("ix_conversations_tenant_status", "tenant_id", "status"),
        Index("ix_conversations_last_activity", "last_activity_at"),
        Index("ix_conversations_session_token", "session_token"),
        Index("ix_conversations_is_lead", "is_lead"),
        Index("ix_conversations_tenant_created", "tenant_id", "created_at"),
    )


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class Messages(Base):
    __tablename__ = "messages"

    # Identity
    id = Column(String, primary_key=True,
                default=uuid7())
    id = Column(String, primary_key=True,
                default=lambda: prefixed_uuid("msg_"))
    conversation_id = Column(String, ForeignKey(
        "conversations.id", ondelete="CASCADE"), nullable=False)

    # Content
    role = Column(Enum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)

    # Performance & Cost Tracking
    tokens_used = Column(Integer, nullable=True)
    model_used = Column(String, nullable=True)
    response_ms = Column(Integer, nullable=True)

    # Timestamp
    created_at = Column(DateTime(timezone=True),
                        nullable=False, default=utcnow)

    # Relationship
    conversation = relationship("Conversation", back_populates="messages")

    # Indexes
    __table_args__ = (
        Index("ix_messages_conversation_created",
              "conversation_id", "created_at"),
        Index("ix_messages_conversation_role", "conversation_id", "role"),
        Index("ix_messages_conversation_model",
              "conversation_id", "model_used"),
    )
