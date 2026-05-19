# app/modules/billing/models.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey,
    Index, Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from typing import TYPE_CHECKING

from app.core.db_base import Base, PublicIdMixin, TimestampMixin
from app.core.enums import (
    BillingInterval, SubscriptionStatus, AddonType, UsageMetric,
    billing_interval_enum, subscription_status_enum,
    addon_type_enum, usage_metric_enum,
)

if TYPE_CHECKING:
    from app.modules.tenants.models import Tenant
    from app.modules.users.models import User


class Plan(Base, PublicIdMixin, TimestampMixin):
    """
    Platform plan catalogue. You manage this — tenants never touch it.

    limits JSONB keys:
        max_users                   → team seat limit
        max_chatbots                → number of chatbot configs allowed
        max_conversations_per_month → new sessions per month (quota)
        max_tokens_per_month        → total tokens across all conversations
        max_tokens_per_conversation → per-conversation token cap
        max_documents               → uploaded document count
        max_pages_crawled           → website pages crawled
        max_listings                → property listings
        max_storage_mb              → document storage in MB

    Changing limits:
        PATCH /admin/plans/{id}  →  { "limits": { ... } }
        Takes effect immediately for all tenants on this plan.
        No migration or deployment needed.
    """
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )

    name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="Display name e.g. Project Developments, Single Office Businesses"
    )
    slug: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True,
        comment="URL-safe unique key e.g. project-developments-monthly"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    billing_interval: Mapped[BillingInterval] = mapped_column(
        billing_interval_enum,
        nullable=False,
        default=BillingInterval.MONTHLY,
        server_default=text("'monthly'"),
    )

    # Prices stored in cents to avoid float precision issues
    price_aud_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="AUD price in cents. e.g. 30000 = AUD 300.00"
    )
    price_usd_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="USD price in cents. 0 = AUD only plan"
    )

    # All entitlement caps in one blob
    # Always read whole — never filter or sort inside
    limits: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        comment=(
            "Entitlement caps. Keys: max_users, max_chatbots, "
            "max_conversations_per_month, max_tokens_per_month, "
            "max_tokens_per_conversation, max_documents, "
            "max_pages_crawled, max_listings, max_storage_mb. "
            "Update via API — no migration needed."
        )
    )

    # Stripe placeholders — populate when Stripe is integrated
    stripe_monthly_price_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="STRIPE_HOOK: Stripe price ID for monthly billing"
    )
    stripe_annual_price_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="STRIPE_HOOK: Stripe price ID for annual billing"
    )

    is_active:  Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("TRUE"),
        comment="FALSE = archived plan, no new subscriptions allowed"
    )
    is_public:  Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("TRUE"),
        comment="FALSE = hidden from tenant plan selection (e.g. custom enterprise plans)"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="Display order on pricing page. Lower = shown first"
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    subscriptions: Mapped[list["TenantSubscription"]] = relationship(
        "TenantSubscription",
        back_populates="plan",
        lazy="noload",
    )
    user_subscriptions: Mapped[list["UserSubscription"]] = relationship(
        "UserSubscription",
        back_populates="plan",
        lazy="noload",
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_plans_slug", "slug"),
        Index("ix_plans_active_public", "is_active", "is_public", "sort_order"),
    )

    # ── Helpers ───────────────────────────────────────────────────────────────
    def get_limit(self, key: str, default: int = 0) -> int:
        """Safe limit getter with default fallback."""
        return int(self.limits.get(key, default))

    @property
    def price_aud(self) -> float:
        return self.price_aud_cents / 100

    @property
    def price_usd(self) -> float:
        return self.price_usd_cents / 100

    def __repr__(self) -> str:
        return f"<Plan slug={self.slug!r} interval={self.billing_interval}>"


class Addon(Base, PublicIdMixin, TimestampMixin):
    """
    Platform addon catalogue. Individual purchasable extras.

    config JSONB structure:
        { "grants_per_unit": { "max_users": 1 } }
        { "grants_per_unit": { "max_conversations_per_month": 250 } }
        { "grants_per_unit": { "max_storage_mb": 5000 } }
        { "grants_per_unit": { "premium_widget": 1 } }

    effective_grant = grants_per_unit[metric] * quantity_purchased
    """
    __tablename__ = "addons"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )

    name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="Display name e.g. Extra User Seat"
    )
    slug: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True,
        comment="URL-safe unique key e.g. extra-users"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    type: Mapped[AddonType] = mapped_column(
        addon_type_enum, nullable=False,
        comment="Addon category — drives which limit key is incremented"
    )

    price_aud_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="Per unit per billing interval in AUD cents"
    )
    price_usd_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="Per unit per billing interval in USD cents"
    )

    # What each purchased unit grants
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment='e.g. { "grants_per_unit": { "max_users": 1 } }'
    )

    # Stripe placeholder
    stripe_price_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="STRIPE_HOOK: Stripe price ID for this addon"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("TRUE")
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    addon_subscriptions: Mapped[list["TenantAddonSubscription"]] = relationship(
        "TenantAddonSubscription",
        back_populates="addon",
        lazy="noload",
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_addons_slug", "slug"),
        Index(
            "ix_addons_type_active", "type",
            postgresql_where=text("is_active = TRUE")
        ),
    )

    # ── Helpers ───────────────────────────────────────────────────────────────
    def grants_per_unit(self, metric: str) -> int:
        """How much of a metric each purchased unit grants."""
        return int(self.config.get("grants_per_unit", {}).get(metric, 0))

    @property
    def price_aud(self) -> float:
        return self.price_aud_cents / 100

    @property
    def price_usd(self) -> float:
        return self.price_usd_cents / 100

    def __repr__(self) -> str:
        return f"<Addon slug={self.slug!r} type={self.type}>"


class TenantSubscription(Base, PublicIdMixin, TimestampMixin):
    """
    Active subscription linking a tenant to a plan.

    Gate 2 check:
        trialing / active  → allow operations
        past_due           → read-only (degrade)
        cancelled / paused → block all writes

    Written by:
        Now  → admin API (manual payment received)
        Later → Stripe webhook handler

    One active subscription per tenant at a time.
    Old subscriptions are kept for billing history.
    """
    __tablename__ = "tenant_subscriptions"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )

    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("plans.id"),
        nullable=False,
    )

    status: Mapped[SubscriptionStatus] = mapped_column(
        subscription_status_enum,
        nullable=False,
        default=SubscriptionStatus.TRIALING,
        server_default=text("'trialing'"),
        comment=(
            "trialing/active=ok | past_due=read-only | "
            "cancelled/paused=block all writes"
        )
    )

    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", server_default=text("'USD'"),
        comment="USD or AUD — determines which price column was used"
    )

    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Start of current billing period"
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="End of current billing period. Reset monthly by Celery task."
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="When trial expires. NULL = not in trial."
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="When subscription was cancelled."
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("FALSE"),
        comment="TRUE = cancel at end of current period, not immediately"
    )

    # Admin billing notes — manual payment tracking
    notes: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment=(
            "Admin payment notes. "
            "e.g. 'Paid AUD 300 via bank transfer on 2026-04-09. Ref: INV-001'"
        )
    )

    # Stripe placeholders — populate when Stripe is integrated
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True,
        comment="STRIPE_HOOK: Stripe subscription ID"
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="STRIPE_HOOK: Stripe customer ID"
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    tenant: Mapped["Tenant"] = relationship(
        "Tenant", back_populates="subscriptions", lazy="noload"
    )
    plan: Mapped["Plan"] = relationship(
        "Plan", back_populates="subscriptions", lazy="noload"
    )
    addon_subscriptions: Mapped[list["TenantAddonSubscription"]] = relationship(
        "TenantAddonSubscription",
        back_populates="subscription",
        lazy="noload",
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_tenant_subs_tenant", "tenant_id"),
        Index("ix_tenant_subs_status", "status"),
        Index("ix_tenant_subs_stripe", "stripe_subscription_id"),
    )

    # ── Helpers ───────────────────────────────────────────────────────────────
    @property
    def is_active(self) -> bool:
        return self.status in (
            SubscriptionStatus.TRIALING,
            SubscriptionStatus.ACTIVE,
        )

    @property
    def is_blocked(self) -> bool:
        return self.status in (
            SubscriptionStatus.CANCELLED,
            SubscriptionStatus.PAUSED,
        )

    @property
    def is_past_due(self) -> bool:
        return self.status == SubscriptionStatus.PAST_DUE

    def __repr__(self) -> str:
        return (
            f"<TenantSubscription "
            f"tenant={self.tenant_id} "
            f"plan={self.plan_id} "
            f"status={self.status}>"
        )


class TenantAddonSubscription(Base, PublicIdMixin, TimestampMixin):
    """
    Purchased addons on top of the base plan.

    Gate 3 effective limit calculation:
        effective_limit = plan.limits[metric]
                        + SUM(addon.grants_per_unit(metric) * quantity)

    One row per (tenant_id, addon_id) — UNIQUE enforced at DB level.
    To increase quantity: UPDATE quantity = quantity + N.
    To cancel: UPDATE status = 'cancelled'.
    """
    __tablename__ = "tenant_addon_subscriptions"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )

    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    addon_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("addons.id"),
        nullable=False,
    )
    subscription_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("tenant_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        comment="Links addon to base subscription for billing cycle alignment"
    )

    status: Mapped[SubscriptionStatus] = mapped_column(
        subscription_status_enum,
        nullable=False,
        default=SubscriptionStatus.ACTIVE,
        server_default=text("'active'"),
    )

    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1"),
        comment="Units purchased. effective_grant = grants_per_unit * quantity"
    )

    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", server_default=text("'USD'")
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Stripe placeholder
    stripe_subscription_item_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="STRIPE_HOOK: Stripe subscription item ID for this addon"
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    addon: Mapped["Addon"] = relationship(
        "Addon", back_populates="addon_subscriptions", lazy="noload"
    )
    subscription: Mapped["TenantSubscription | None"] = relationship(
        "TenantSubscription", back_populates="addon_subscriptions", lazy="noload"
    )

    # ── Constraints & indexes ─────────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint("tenant_id", "addon_id", name="uq_tenant_addon"),
        Index("ix_tenant_addon_subs_tenant", "tenant_id"),
        Index("ix_tenant_addon_subs_status", "tenant_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<TenantAddonSubscription "
            f"tenant={self.tenant_id} "
            f"addon={self.addon_id} "
            f"qty={self.quantity} "
            f"status={self.status}>"
        )


class UsageRecord(Base):
    """
    One row per metric per tenant per month.

    Update pattern:
        Real-time  → Celery task increments on every event
        Hourly     → reconciliation task cross-checks vs actual DB counts

    Quota enforcement:
        conversations → checked before starting new session
                        current session continues when limit hit
                        new sessions blocked at 100%
        tokens_used   → checked before processing each message
                        blocked at 100%

    Warning flags:
        warned_80 → set when usage crosses 80%, email sent once per period
        warned_90 → set when usage crosses 90%, email sent once per period
        Flags reset automatically next month (new period_month = new row)
    """
    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )

    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    metric: Mapped[UsageMetric] = mapped_column(
        usage_metric_enum, nullable=False,
        comment=(
            "conversations | messages | tokens_used | "
            "pages_crawled | documents_uploaded | active_users"
        )
    )

    quantity: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0"),
        comment="Cumulative count for this metric in this billing period"
    )

    # Billing period — YYYY-MM format e.g. '2026-04'
    # New month = new row automatically via upsert
    period_month: Mapped[str] = mapped_column(
        String(7), nullable=False,
        comment="Billing period in YYYY-MM format e.g. '2026-04'"
    )

    # Warning flags — set once per period, never reset within same period
    warned_80: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("FALSE"),
        comment="TRUE after 80% warning notification sent this period"
    )
    warned_90: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("FALSE"),
        comment="TRUE after 90% warning notification sent this period"
    )

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("(NOW() AT TIME ZONE 'UTC')"),
        comment="Last time this record was updated"
    )

    # ── Constraints & indexes ─────────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "metric", "period_month",
            name="uq_usage_tenant_metric_month"
        ),
        Index("ix_usage_tenant_period", "tenant_id", "period_month"),
        Index("ix_usage_metric_period", "metric", "period_month"),
    )

    def __repr__(self) -> str:
        return (
            f"<UsageRecord "
            f"tenant={self.tenant_id} "
            f"metric={self.metric} "
            f"period={self.period_month} "
            f"qty={self.quantity}>"
        )


class UserSubscription(Base, PublicIdMixin, TimestampMixin):
    """
    Platform-level subscription owned by a user (the owner/payer).

    The user buys a plan before creating any tenants. The plan limits
    (including max_tenants) govern what they can create.

    Gate behaviour:
        active / trialing  → can create tenants up to plan.max_tenants
        past_due           → degraded access; tenant creation blocked
        cancelled / paused → tenant creation blocked
    """
    __tablename__ = "user_subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("plans.id"),
        nullable=False,
    )

    status: Mapped[SubscriptionStatus] = mapped_column(
        subscription_status_enum,
        nullable=False,
        default=SubscriptionStatus.ACTIVE,
        server_default=text("'active'"),
    )

    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", server_default=text("'USD'"),
        comment="USD or AUD — matches the Stripe price currency"
    )

    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("FALSE"),
        comment="TRUE = cancel at end of current period, not immediately"
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True,
        comment="STRIPE_HOOK: Stripe subscription ID"
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="STRIPE_HOOK: Stripe customer ID"
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    plan: Mapped["Plan"] = relationship(
        "Plan", back_populates="user_subscriptions", lazy="noload"
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_user_subs_user", "user_id"),
        Index("ix_user_subs_status", "status"),
        Index("ix_user_subs_stripe", "stripe_subscription_id"),
    )

    # ── Helpers ───────────────────────────────────────────────────────────────
    @property
    def is_active(self) -> bool:
        return self.status in (SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE)

    @property
    def is_blocked(self) -> bool:
        return self.status in (SubscriptionStatus.CANCELLED, SubscriptionStatus.PAUSED)

    @property
    def is_past_due(self) -> bool:
        return self.status == SubscriptionStatus.PAST_DUE

    def __repr__(self) -> str:
        return (
            f"<UserSubscription "
            f"user={self.user_id} "
            f"plan={self.plan_id} "
            f"status={self.status}>"
        )