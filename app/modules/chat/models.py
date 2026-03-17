"""
models.py — SQLAlchemy ORM models for the chat module.

Identity strategy
─────────────────
  - `id`        : internal surrogate PK (BigInteger autoincrement) — NEVER exposed via API.
                  Used for all FK joins internally (fast, sequential, 8 bytes).
  - `public_id` : uuid7 string — time-sortable, globally unique, non-predictable.
                  Exposed in every API response. Used as the external identifier
                  in URL paths and pagination cursors.

Why uuid7 for public_id?
  - Time-sortable: first 48 bits are a millisecond timestamp, so ORDER BY public_id
    approximates ORDER BY created_at — enables keyset pagination with a single column.
  - Non-sequential: unlike auto-increment IDs, clients cannot enumerate records.
  - Globally unique: safe for distributed inserts without coordination.
"""

import uuid
import enum
from datetime import datetime, timezone

from uuid6 import uuid7
from sqlalchemy import (
    ARRAY, Column, String, Text, Integer, BigInteger, Boolean,
    DateTime, Enum, ForeignKey, Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import ENUM
from app.core.db_base import Base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def prefixed_uuid4(prefix: str) -> str:
    """
    Internal PK generator — prefixed uuid4 hex.
    Example: 'conv_3f2504e04f8911d39a0c0305e82c3301'
    Never exposed externally.
    """
    return f"{prefix}{uuid.uuid4().hex}"


def new_public_id() -> str:
    """
    Public identifier generator — uuid7 string.
    Example: '018e7b1a-1234-7abc-8def-0123456789ab'
    Time-sortable, non-predictable. Used in all API responses and URL paths.
    """
    return str(uuid7())


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ConversationStatus(str, enum.Enum):
    in_progress = "in_progress"
    closed      = "closed"
    summarized  = "summarized"
    emailed     = "emailed"
    archived    = "archived"
    
    # PostgreSQL enum for database
    conversationstatus_enum = ENUM(
        'in_progress', 'closed', 'summarized', 'emailed', 'archived',
        name='conversationstatus',
        create_type=False   # avoids trying to recreate in migrations
    )



class MessageRole(str, enum.Enum):
    user      = "user"
    assistant = "assistant"
    system    = "system"


class ChatbotIdentity(str, enum.Enum):
    website = "website"
    veloce_demo = "veloce_demo"



# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Conversation(Base):
    __tablename__ = "conversations"

    # ── Identity ─────────────────────────────────────────────────────────────
    id = Column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Internal surrogate PK. Never exposed via API.",
    )
    public_id = Column(
        String,
        unique=True,
        nullable=False,
        default=new_public_id,
        comment="External identifier (uuid7). Exposed in all API responses.",
    )
    tenant_id = Column(
        String,
        nullable=False,
        comment="Tenant scoping key for multi-tenancy.",
    )
    session_token = Column(
        String,
        unique=True,
        nullable=False,
        default=lambda: prefixed_uuid4("sess_"),
        comment="Anonymous session token for widget-based chats.",
    )
    identity_hash = Column(
        String,
        nullable=True,
        comment="Optional hashed identity for returning visitor recognition.",
    )

    # ── Visitor Info ─────────────────────────────────────────────────────────
    visitor_ip_hash = Column(String, nullable=True)
    visitor_ua      = Column(String, nullable=True)
    page_url        = Column(String, nullable=True)

    # ── Status & Lifecycle ───────────────────────────────────────────────────
    status = Column(
        Enum(ConversationStatus),
        nullable=False,
        default=ConversationStatus.in_progress,
    )

    # ── Lead Capture ─────────────────────────────────────────────────────────
    is_lead    = Column(Boolean, nullable=False, default=False)
    lead_name  = Column(String,  nullable=True)
    lead_email = Column(String,  nullable=True)
    lead_phone = Column(String,  nullable=True)

    # ── Counters (denormalized for fast reads — avoids COUNT(*) on messages) ─
    total_messages    = Column(Integer, nullable=False, default=0)
    total_tokens_used = Column(Integer, nullable=False, default=0)

    # ── LLM Context ──────────────────────────────────────────────────────────
    running_summary = Column(
        Text,
        nullable=True,
        comment="Rolling summary updated as the conversation grows (context compression).",
    )
    summary = Column(
        Text,
        nullable=True,
        comment="Final summary generated when the conversation is closed.",
    )

    # ── Archival ─────────────────────────────────────────────────────────────
    archive_url = Column(String, nullable=True)

    # ── Timestamps ───────────────────────────────────────────────────────────
    last_activity_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        comment="Updated on every message. Used for idle-timeout detection.",
    )
    closed_at  = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    # ── Relationships ─────────────────────────────────────────────────────────
    # lazy="select" means SQLAlchemy will NOT auto-load messages when you
    # fetch a Conversation. All loading is explicit via selectinload/joinedload
    # in repository queries — this prevents accidental N+1 queries.
    messages = relationship(
        "Message",
        back_populates="conversation",
        order_by="Message.created_at",
        lazy="select",
        cascade="all, delete-orphan",
        passive_deletes=True,       # rely on DB-level CASCADE (ondelete="CASCADE")
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        # Fast lookup by public_id (used in every API route)
        Index("ix_conversations_public_id",     "public_id"),

        # Keyset pagination: tenant + time + public_id gives a stable cursor
        # that the DB can satisfy with an index range scan — no OFFSET needed
        Index("ix_conversations_tenant_cursor", "tenant_id", "created_at", "public_id"),

        # Status-filtered list views (e.g. show only in_progress conversations)
        Index("ix_conversations_tenant_status", "tenant_id", "status"),

        # Idle-timeout detection and activity dashboards
        Index("ix_conversations_last_activity", "last_activity_at"),

        # Session token lookup (anonymous widget reconnects)
        Index("ix_conversations_session_token", "session_token"),

        # Lead filtering for CRM integrations
        Index("ix_conversations_is_lead",       "is_lead"),
    )

    def __repr__(self) -> str:
        return (
            f"<Conversation public_id={self.public_id!r} "
            f"tenant={self.tenant_id!r} status={self.status!r}>"
        )


class Message(Base):
    __tablename__ = "messages"

    # ── Identity ─────────────────────────────────────────────────────────────
    id = Column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Internal surrogate PK. Never exposed via API.",
    )
    public_id = Column(
        String,
        unique=True,
        nullable=False,
        default=new_public_id,
        comment="External identifier (uuid7). Returned in API responses.",
    )
    conversation_id = Column(
        BigInteger,                                        # must match Conversation.id type
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK to conversations.id (internal PK). Cascades on delete.",
    )

    # ── Content ───────────────────────────────────────────────────────────────
    role    = Column(Enum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)

    # ── Performance & Cost Tracking ───────────────────────────────────────────
    tokens_used = Column(
        Integer,
        nullable=True,
        comment="Token count for this message (input + output for assistant turns).",
    )
    model_used = Column(
        String,
        nullable=True,
        comment="LLM model identifier, e.g. 'gpt-4o'. Null for user messages.",
    )
    response_ms = Column(
        Integer,
        nullable=True,
        comment="LLM response latency in milliseconds. Null for user messages.",
    )

    # ── Timestamp ─────────────────────────────────────────────────────────────
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    # ── Relationships ─────────────────────────────────────────────────────────
    conversation = relationship(
        "Conversation",
        back_populates="messages",
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        # Primary access pattern: all messages for a conversation in order.
        # Used by selectinload batching, get_conversation_history, and detail views.
        Index("ix_messages_conv_created", "conversation_id", "created_at"),

        # Role filter within a conversation (e.g. fetch only assistant turns
        # for analytics or re-summarization jobs)
        Index("ix_messages_conv_role",    "conversation_id", "role"),

        # Public ID lookup (e.g. reference a specific message by ID in the API)
        Index("ix_messages_public_id",    "public_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Message public_id={self.public_id!r} "
            f"role={self.role!r} conv={self.conversation_id!r}>"
        )


class ConversationInsights(Base):
    __tablename__ = "conversation_insights"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(BigInteger, ForeignKey(
        "conversations.id", ondelete="CASCADE"), unique=True, nullable=False)
    # ALWAYS denormalized here for fast dashboard queries
    tenant_id = Column(String, nullable=False)

    # ── Lead Scoring ─────────────────────────────────────────────────────────
    lead_score = Column(Integer, nullable=True)   # 0–100, LLM-generated
    lead_tier = Column(String,  nullable=True)   # "hot" | "nurture" | "cold"
    # "buy" | "rent" | "invest" | "browse"
    intent = Column(String,  nullable=True)

    # ── Real Estate Specifics ─────────────────────────────────────────────────
    budget_min = Column(Integer, nullable=True)   # extracted PKR/USD value
    budget_max = Column(Integer, nullable=True)
    budget_currency = Column(String,  nullable=True)   # "PKR" | "USD"
    # ["DHA", "Bahria Town", "Gulberg"]
    suburbs_mentioned = Column(ARRAY(String), nullable=True)
    cities_mentioned = Column(ARRAY(String), nullable=True)
    # ["apartment", "plot", "house"]
    property_types = Column(ARRAY(String), nullable=True)
    bedrooms_wanted = Column(Integer, nullable=True)
    # "immediate" | "3_months" | "6_months" | "browsing"
    timeline = Column(String,  nullable=True)

    # ── Sentiment & Engagement ────────────────────────────────────────────────
    # "positive" | "neutral" | "negative"
    sentiment = Column(String,  nullable=True)
    # based on message count, depth
    engagement_score = Column(Integer, nullable=True)

    # ── Topics (for heatmap + frequency analysis) ─────────────────────────────
    # ["payment plan", "NOC", "possession"]
    topics_mentioned = Column(ARRAY(String), nullable=True)

    # ── AI Narrative ──────────────────────────────────────────────────────────
    # 2-3 sentence human-readable summary
    ai_summary = Column(Text, nullable=True)
    # trend observations for this conversation
    ai_insights = Column(Text, nullable=True)

    # ── Processing State ──────────────────────────────────────────────────────
    processed_at = Column(DateTime(timezone=True), nullable=True)
    # "v1.2" — lets you reprocess if prompt changes
    processing_version = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_insights_tenant_id",        "tenant_id"),
        Index("ix_insights_tenant_lead_tier", "tenant_id", "lead_tier"),
        Index("ix_insights_tenant_intent",    "tenant_id", "intent"),
        Index("ix_insights_tenant_budget",
              "tenant_id", "budget_min", "budget_max"),
        Index("ix_insights_conversation_id",  "conversation_id"),
    )
