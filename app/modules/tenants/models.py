# models/tenant.py
"""
Tenant model — root of the multi-tenant hierarchy.

One row per company / agency that signs up to the platform.
Every tenant-scoped table has a tenant_id FK pointing here.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IDENTITY STRATEGY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  id         BIGSERIAL (integer PK)  — internal, used for all FK joins.
                                        NEVER exposed via API.
  public_id  VARCHAR (uuid7)         — time-sortable, non-predictable.
                                        Exposed in every API response and URL.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS GATE (Gate 1 — checked first in every middleware)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  pending_plan → redirect to paywall (no plan selected yet)
  trial        → plan selected, within free trial window
  active       → paying, trial has ended
  suspended    → manually suspended or payment failure
  cancelled    → churned; block all access

  To disable a tenant in one query:
      UPDATE tenants SET status = 'suspended' WHERE id = X
  Middleware Gate 1 handles the rest — no cascade logic needed.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FLAT COLUMNS vs JSONB — Decision record
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Flat:
    name          — admin search, display
    slug          — UNIQUE index, URL path segment
    status        — WHERE, middleware gate check
    industry      — future filtering / analytics
    trial_ends_at — background job compares vs NOW()

  JSONB (settings):
    Whole-unit config blob: timezone, logo_url, support_email, etc.
    Never filtered or sorted inside → JSONB appropriate.
    Always read whole when rendering tenant context.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INDEXES — Decision record
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ix_tenants_public_id — every API read is by public_id
  ix_tenants_slug      — login/domain routing lookup
  ix_tenants_status    — middleware gate, admin dashboard; partial (not deleted)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, String, Index, text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_base import Base, PublicIdMixin, TimestampMixin, SoftDeleteMixin
from app.core.enums import TenantStatus, tenant_status_enum, TenantRole, tenant_role_enum

if TYPE_CHECKING:
    from app.modules.models.tenant_user import TenantUser
    from app.modules.billing.models import TenantSubscription
    from app.modules.chatbot.models import ChatbotConfig
    from app.modules.models.otp import OTPVerification
    from app.modules.users.models import User


class Tenant(Base, PublicIdMixin, TimestampMixin, SoftDeleteMixin):
    """
    Root of the multi-tenant hierarchy.

    Security notes:
    - The integer `id` is NEVER returned by any API endpoint.
      All external references use `public_id` (uuid7).
    - slug is safe to expose in URLs (url-safe, not guessable as a surrogate key).
    - settings JSONB must never contain secrets — use a secrets manager for API keys.

    Usage examples:

        # Create
        tenant = Tenant(
            name     = "Acme Realty",
            slug     = "acme-realty",
            industry = "real_estate",
            settings = {"timezone": "Australia/Sydney", "logo_url": "..."},
        )
        # Gate 1 check
        if tenant.status in (TenantStatus.SUSPENDED, TenantStatus.CANCELLED):
            raise HTTPException(403)
        if tenant.status == TenantStatus.PENDING_PLAN:
            raise HTTPException(402)   # redirect to paywall
    """

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )

    # ── Core identity ─────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Company / agency display name.",
    )

    slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        comment=(
            "URL-safe identifier, e.g. 'acme-realty'. "
            "Used in routing and subdomain resolution. Immutable after creation."
        ),
    )

    industry: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="real_estate",
        server_default=text("'real_estate'"),
        comment="Industry vertical. Used for analytics and future vertical-specific features.",
    )

    # ── Status (Gate 1) ───────────────────────────────────────────────────────
    status: Mapped[TenantStatus] = mapped_column(
        tenant_status_enum,
        nullable=False,
        default=TenantStatus.PENDING_PLAN,
        server_default=text("'pending_plan'"),
        comment=(
            "pending_plan=paywall gate | trial=free trial | active=paying | "
            "suspended=blocked | cancelled=churned. "
            "Single UPDATE here controls access — middleware Gate 1 reads this."
        ),
    )

    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment=(
            "When the trial period expires. "
            "Background job transitions status → 'active' or 'suspended' at this time."
        ),
    )

    # ── Config blob ───────────────────────────────────────────────────────────
    settings: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        comment=(
            "Whole-unit config: timezone, logo_url, support_email, etc. "
            "Always read as a complete blob — never filter or sort inside. "
            "Do NOT store secrets here; use a secrets manager."
        ),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    tenant_users: Mapped[list["TenantUser"]] = relationship(
        "TenantUser",
        back_populates="tenant",
        lazy="noload",
        cascade="all, delete-orphan",
    )

    subscriptions: Mapped[list["TenantSubscription"]] = relationship(
        "TenantSubscription",
        back_populates="tenant",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="TenantSubscription.created_at.desc()",
    )

    chatbots: Mapped[list["ChatbotConfig"]] = relationship(
        "ChatbotConfig",
        back_populates="tenant",
        lazy="noload",
        cascade="all, delete-orphan",
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        # Every API read is by public_id — covered by PublicIdMixin unique=True
        # but named explicitly for pg_stat_user_indexes visibility.
        Index("ix_tenants_public_id", "public_id"),

        # Domain / subdomain routing lookup.
        Index("ix_tenants_slug", "slug"),

        # Middleware Gate 1 check + admin dashboard filter.
        # Partial: skip soft-deleted tenants.
        Index(
            "ix_tenants_status",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    # ── Computed helpers ──────────────────────────────────────────────────────
    @property
    def is_accessible(self) -> bool:
        """
        True when the tenant can perform normal operations.
        Use for quick in-memory gate checks after the middleware already
        loaded the tenant; don't use as a substitute for middleware.
        """
        return self.status in (TenantStatus.TRIAL, TenantStatus.ACTIVE)

    @property
    def is_blocked(self) -> bool:
        return self.status in (TenantStatus.SUSPENDED, TenantStatus.CANCELLED)

    @property
    def needs_plan(self) -> bool:
        return self.status == TenantStatus.PENDING_PLAN

    def __repr__(self) -> str:
        return (
            f"<Tenant id={self.id} slug={self.slug!r} status={self.status}>"
        )


class TenantInvite(Base, PublicIdMixin, TimestampMixin):
    """
    Tracks every invite sent to a user for a tenant.

    Purpose:
    - Store invite metadata (tenant, role, invited_by) reliably in DB instead of Redis.
    - Enforce 72-hour resend restriction: at most one invite per (tenant, invitee) per 72h.
    - Allow accept_invite to resolve tenant/role without Redis.

    The `otp_id` links to the OTPVerification row that holds the hashed code.
    When the invite is accepted, `consumed_at` is set here (OTP is also consumed).
    """

    __tablename__ = "tenant_invites"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    invitee_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    invited_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    role: Mapped[TenantRole] = mapped_column(
        tenant_role_enum,
        nullable=False,
    )

    otp_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("otp_verifications.id", ondelete="SET NULL"),
        nullable=True,
    )

    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="When this invite email was dispatched. Used for 72h resend restriction.",
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    consumed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Set when the invitee accepts. NULL = pending.",
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    tenant: Mapped["Tenant"] = relationship("Tenant", foreign_keys=[tenant_id], lazy="noload")
    invitee: Mapped["User"] = relationship("User", foreign_keys=[invitee_user_id], lazy="noload")
    otp: Mapped[Optional["OTPVerification"]] = relationship(
        "OTPVerification", foreign_keys=[otp_id], lazy="noload"
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_tenant_invites_tenant_invitee", "tenant_id", "invitee_user_id"),
        Index("ix_tenant_invites_otp_id", "otp_id"),
    )

    def __repr__(self) -> str:
        return f"<TenantInvite tenant={self.tenant_id} invitee={self.invitee_user_id} consumed={self.consumed_at is not None}>"
