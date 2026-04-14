# app/modules/campaigns/models.py
"""
Campaign model — a tenant-scoped, chatbot-specific overlay that customises
the system prompt based on which page the visitor is on.

Design decisions
────────────────
- NO separate iframe_token. The chatbot iframe is embedded once and never
  changes. The backend selects the appropriate campaign by matching the
  visitor's page_url against each campaign's url_patterns list.

- url_patterns is a JSONB list of substring patterns (e.g. ["/contact-us"]).
  An empty list means no URL targeting — used in combination with is_default=True
  to mark a catch-all campaign.

- is_default: when True, this campaign applies whenever no url_patterns match.
  Only one campaign per chatbot should be marked as default; enforced at the
  service layer (not a DB constraint, to avoid migration churn).

- prompt_overlay: free-text instructions injected between the static base
  (personality + company profile) and the dynamic RAG suffix at chat time.
  Max 4000 chars — enough for a focused paragraph or two.

- sort_order: when multiple campaigns' url_patterns all match the same page URL,
  the one with the lowest sort_order wins. Defaults to 0.

- campaign_id on Conversation: set once at conversation start (URL match),
  never changed mid-conversation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_base import Base, PublicIdMixin, TimestampMixin
from app.core.enums import CampaignStatus, campaign_status_enum

if TYPE_CHECKING:
    from app.modules.chatbot.models import ChatbotConfig


class Campaign(Base, PublicIdMixin, TimestampMixin):
    """
    A named campaign overlay for a specific ChatbotConfig.

    One chatbot can have many campaigns. Each campaign customises what the
    AI says on a given page or set of pages — without changing the iframe.
    """
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ── Ownership ─────────────────────────────────────────────────────────────
    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        comment="Denormalized — allows direct tenant-scoped queries without joining chatbot_configs.",
    )
    chatbot_config_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chatbot_configs.id", ondelete="CASCADE"),
        nullable=False,
        comment="The base chatbot whose knowledge, personality, and company profile this campaign uses.",
    )

    # ── Identity ──────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Human-readable campaign name shown in the admin portal. E.g. 'Contact Us Campaign'.",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="Optional internal description. Not shown to visitors.",
    )

    # ── Status ────────────────────────────────────────────────────────────────
    status: Mapped[CampaignStatus] = mapped_column(
        campaign_status_enum,
        nullable=False,
        default=CampaignStatus.DRAFT,
        server_default=text("'draft'"),
    )

    # ── URL targeting ─────────────────────────────────────────────────────────
    url_patterns: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        comment=(
            "List of URL substrings that trigger this campaign. "
            "E.g. [\"/contact-us\", \"/get-in-touch\"]. "
            "Matching is case-insensitive substring: the visitor's page_url must contain "
            "at least one pattern. Empty list = no URL targeting (use is_default instead)."
        ),
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
        comment=(
            "When True, this campaign is the catch-all fallback for this chatbot — "
            "applied when no other active campaign's url_patterns match the visitor's page. "
            "Only one campaign per chatbot should be marked is_default=True. "
            "Enforced at the service layer."
        ),
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment=(
            "Priority when multiple campaigns match the same page URL. "
            "Lower number = higher priority. Campaigns with the same sort_order "
            "are resolved by created_at (most recent wins)."
        ),
    )

    # ── Welcome message ───────────────────────────────────────────────────────
    welcome_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment=(
            "First message shown in the chatbot widget when a visitor lands on a page "
            "matched by this campaign. Overrides the chatbot-level welcome_message. "
            "Falls back to the chatbot welcome_message if NULL."
        ),
    )

    # ── System prompt overlay ─────────────────────────────────────────────────
    prompt_overlay: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment=(
            "Campaign-specific instructions injected into the system prompt between "
            "the static base (personality + company profile) and the dynamic RAG suffix. "
            "Keep focused: tone adjustments, goal reminders, specific CTAs. Max ~4000 chars."
        ),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    chatbot_config: Mapped["ChatbotConfig"] = relationship(
        "ChatbotConfig",
        back_populates="campaigns",
        lazy="noload",
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_campaigns_tenant", "tenant_id"),
        Index("ix_campaigns_chatbot", "chatbot_config_id"),
        Index("ix_campaigns_tenant_status", "tenant_id", "status"),
        Index("ix_campaigns_chatbot_status", "chatbot_config_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Campaign id={self.id} name={self.name!r} status={self.status} default={self.is_default}>"
