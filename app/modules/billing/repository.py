# app/modules/billing/repository.py
from __future__ import annotations

import logging
from typing import Optional, List

logger = logging.getLogger(__name__)

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.billing.models import (
    Plan, Addon,
    TenantSubscription, TenantAddonSubscription,
    UsageRecord, UserSubscription,
)
from app.core.enums import SubscriptionStatus, UsageMetric


# =============================================================================
# PLAN READS
# =============================================================================

async def get_plan_by_id(db: AsyncSession, *, plan_id: int) -> Optional[Plan]:
    result = await db.execute(select(Plan).where(Plan.id == plan_id))
    return result.scalar_one_or_none()


async def get_plan_by_slug(db: AsyncSession, *, slug: str) -> Optional[Plan]:
    result = await db.execute(select(Plan).where(Plan.slug == slug))
    return result.scalar_one_or_none()


async def get_plan_by_public_id(db: AsyncSession, *, public_id: str) -> Optional[Plan]:
    result = await db.execute(select(Plan).where(Plan.public_id == public_id))
    return result.scalar_one_or_none()


async def list_public_plans(db: AsyncSession) -> List[Plan]:
    result = await db.execute(
        select(Plan)
        .where(Plan.is_active == True, Plan.is_public == True)
        .order_by(Plan.sort_order.asc())
    )
    return result.scalars().all()


async def list_all_plans(db: AsyncSession) -> List[Plan]:
    result = await db.execute(
        select(Plan).order_by(Plan.sort_order.asc())
    )
    return result.scalars().all()


# =============================================================================
# PLAN WRITES
# =============================================================================

async def create_plan(db: AsyncSession, *, plan: Plan) -> Plan:
    db.add(plan)
    await db.flush()
    await db.refresh(plan)
    return plan


# =============================================================================
# ADDON READS
# =============================================================================

async def get_addon_by_id(db: AsyncSession, *, addon_id: int) -> Optional[Addon]:
    result = await db.execute(select(Addon).where(Addon.id == addon_id))
    return result.scalar_one_or_none()


async def get_addon_by_public_id(db: AsyncSession, *, public_id: str) -> Optional[Addon]:
    result = await db.execute(select(Addon).where(Addon.public_id == public_id))
    return result.scalar_one_or_none()


async def list_active_addons(db: AsyncSession) -> List[Addon]:
    result = await db.execute(
        select(Addon)
        .where(Addon.is_active == True)
        .order_by(Addon.type)
    )
    return result.scalars().all()


# =============================================================================
# SUBSCRIPTION READS
# =============================================================================

async def get_active_subscription(
    db: AsyncSession, *, tenant_id: int
) -> Optional[TenantSubscription]:
    result = await db.execute(
        select(TenantSubscription)
        .options(selectinload(TenantSubscription.plan))
        .where(
            TenantSubscription.tenant_id == tenant_id,
            TenantSubscription.status.in_([
                SubscriptionStatus.ACTIVE,
                SubscriptionStatus.TRIALING,
                SubscriptionStatus.PAST_DUE,
            ])
        )
        .order_by(TenantSubscription.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_subscription_by_public_id(
    db: AsyncSession, *, public_id: str
) -> Optional[TenantSubscription]:
    result = await db.execute(
        select(TenantSubscription)
        .options(selectinload(TenantSubscription.plan))
        .where(TenantSubscription.public_id == public_id)
    )
    return result.scalar_one_or_none()


# ── Stripe lookup helpers (used by webhook handler) ──────────────────────────

async def get_subscription_by_stripe_subscription_id(
    db: AsyncSession, *, stripe_subscription_id: str
) -> Optional[TenantSubscription]:
    """Resolve our internal subscription row from a Stripe subscription id."""
    result = await db.execute(
        select(TenantSubscription)
        .options(selectinload(TenantSubscription.plan))
        .where(TenantSubscription.stripe_subscription_id == stripe_subscription_id)
    )
    return result.scalar_one_or_none()


async def get_latest_subscription_by_stripe_customer_id(
    db: AsyncSession, *, stripe_customer_id: str
) -> Optional[TenantSubscription]:
    """
    Find the most recent subscription for a Stripe customer.
    Used by webhook handlers when only the customer id is available
    (e.g. invoice.payment_failed for a one-time charge).
    """
    result = await db.execute(
        select(TenantSubscription)
        .options(selectinload(TenantSubscription.plan))
        .where(TenantSubscription.stripe_customer_id == stripe_customer_id)
        .order_by(TenantSubscription.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_plan_by_stripe_price_id(
    db: AsyncSession, *, stripe_price_id: str
) -> Optional[Plan]:
    """
    Resolve a Plan from a Stripe price id (monthly OR annual).
    Used during checkout.session.completed to find which plan was purchased.
    """
    result = await db.execute(
        select(Plan).where(
            (Plan.stripe_monthly_price_id == stripe_price_id)
            | (Plan.stripe_annual_price_id == stripe_price_id)
        )
    )
    return result.scalar_one_or_none()


async def list_tenant_subscriptions(
    db: AsyncSession, *, tenant_id: int
) -> List[TenantSubscription]:
    result = await db.execute(
        select(TenantSubscription)
        .options(selectinload(TenantSubscription.plan))
        .where(TenantSubscription.tenant_id == tenant_id)
        .order_by(TenantSubscription.created_at.desc())
    )
    return result.scalars().all()


# =============================================================================
# ADDON SUBSCRIPTION READS
# =============================================================================

async def get_tenant_addon(
    db: AsyncSession, *, tenant_id: int, addon_id: int
) -> Optional[TenantAddonSubscription]:
    result = await db.execute(
        select(TenantAddonSubscription).where(
            TenantAddonSubscription.tenant_id == tenant_id,
            TenantAddonSubscription.addon_id  == addon_id,
        )
    )
    return result.scalar_one_or_none()


async def list_tenant_addons(
    db: AsyncSession, *, tenant_id: int
) -> List[TenantAddonSubscription]:
    result = await db.execute(
        select(TenantAddonSubscription)
        .options(selectinload(TenantAddonSubscription.addon))
        .where(
            TenantAddonSubscription.tenant_id == tenant_id,
            TenantAddonSubscription.status    == SubscriptionStatus.ACTIVE,
        )
    )
    return result.scalars().all()


async def get_addon_grant_total(
    db: AsyncSession, *, tenant_id: int, metric: str
) -> int:
    """Sum of all active addon grants for a specific metric key."""
    addons = await list_tenant_addons(db, tenant_id=tenant_id)
    return sum(
        tas.addon.grants_per_unit(metric) * tas.quantity
        for tas in addons
    )


async def tenant_has_active_addon(
    db: AsyncSession, *, tenant_id: int, addon_type: "AddonType"
) -> bool:
    """True if tenant has at least one active subscription to an addon of the given type."""
    from app.core.enums import AddonType as _AddonType  # local import to avoid cycle
    addons = await list_tenant_addons(db, tenant_id=tenant_id)
    return any(tas.addon.type == addon_type for tas in addons)


async def tenant_has_premium_model_entitlement(
    db: AsyncSession, *, tenant_id: int
) -> bool:
    """
    True when the tenant is entitled to use the premium chat model (gpt-4.1).
    Entitlement sources:
      1. Active EXTRA_PREMIUM_MODEL add-on subscription, OR
      2. Plan limits include 'includes_premium_model' > 0 (configured per plan tier).
    """
    from app.core.enums import AddonType
    sub = await get_active_subscription(db, tenant_id=tenant_id)
    if sub and sub.plan and sub.plan.get_limit("includes_premium_model"):
        return True
    return await tenant_has_active_addon(
        db, tenant_id=tenant_id, addon_type=AddonType.EXTRA_PREMIUM_MODEL
    )


# =============================================================================
# USAGE READS
# =============================================================================

async def get_usage(
    db: AsyncSession,
    *,
    tenant_id: int,
    metric: UsageMetric,
    period_month: str,
) -> Optional[UsageRecord]:
    result = await db.execute(
        select(UsageRecord).where(
            UsageRecord.tenant_id    == tenant_id,
            UsageRecord.metric       == metric,
            UsageRecord.period_month == period_month,
        )
    )
    return result.scalar_one_or_none()


async def get_all_usage_for_period(
    db: AsyncSession, *, tenant_id: int, period_month: str
) -> List[UsageRecord]:
    result = await db.execute(
        select(UsageRecord).where(
            UsageRecord.tenant_id    == tenant_id,
            UsageRecord.period_month == period_month,
        )
    )
    return result.scalars().all()


# =============================================================================
# USAGE WRITES
# =============================================================================

async def increment_usage(
    db: AsyncSession,
    *,
    tenant_id: int,
    metric: UsageMetric,
    period_month: str,
    amount: int = 1,
) -> None:
    """Atomic upsert — safe for concurrent increments."""
    await db.execute(
        text("""
            INSERT INTO usage_records
                (tenant_id, metric, period_month, quantity, recorded_at)
            VALUES
                (:tenant_id, :metric, :period_month, :amount,
                 NOW() AT TIME ZONE 'UTC')
            ON CONFLICT (tenant_id, metric, period_month)
            DO UPDATE SET
                quantity    = usage_records.quantity + :amount,
                recorded_at = NOW() AT TIME ZONE 'UTC'
        """),
        {
            "tenant_id":    tenant_id,
            "metric":       metric.value,
            "period_month": period_month,
            "amount":       amount,
        }
    )


# =============================================================================
# USER SUBSCRIPTION READS
# =============================================================================

async def get_active_user_subscription(
    db: AsyncSession, *, user_id: int
) -> Optional[UserSubscription]:
    """Return the user's current active/trialing/past_due subscription."""
    result = await db.execute(
        select(UserSubscription)
        .options(selectinload(UserSubscription.plan))
        .where(
            UserSubscription.user_id == user_id,
            UserSubscription.status.in_([
                SubscriptionStatus.ACTIVE,
                SubscriptionStatus.TRIALING,
                SubscriptionStatus.PAST_DUE,
            ])
        )
        .order_by(UserSubscription.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_user_subscription_by_stripe_id(
    db: AsyncSession, *, stripe_subscription_id: str
) -> Optional[UserSubscription]:
    """Resolve a UserSubscription from a Stripe subscription id (used by webhook)."""
    result = await db.execute(
        select(UserSubscription)
        .options(selectinload(UserSubscription.plan))
        .where(UserSubscription.stripe_subscription_id == stripe_subscription_id)
    )
    return result.scalar_one_or_none()


async def get_user_subscription_by_stripe_customer_id(
    db: AsyncSession, *, stripe_customer_id: str
) -> Optional[UserSubscription]:
    """Find the most recent user subscription for a Stripe customer id."""
    result = await db.execute(
        select(UserSubscription)
        .options(selectinload(UserSubscription.plan))
        .where(UserSubscription.stripe_customer_id == stripe_customer_id)
        .order_by(UserSubscription.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def mark_warned(
    db: AsyncSession,
    *,
    tenant_id: int,
    metric: UsageMetric,
    period_month: str,
    level: int,
) -> None:
    """Mark warning flag on usage record. level = 80 or 90."""
    record = await get_usage(
        db, tenant_id=tenant_id, metric=metric, period_month=period_month
    )
    if record:
        if level == 80:
            record.warned_80 = True
        elif level == 90:
            record.warned_90 = True
        await db.flush()