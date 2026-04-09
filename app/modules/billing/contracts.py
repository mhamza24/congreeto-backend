# app/modules/billing/contracts.py
"""
Stripe-ready billing contracts.
All billing state changes go through here.
Right now → writes directly to DB.
Later     → add Stripe API calls alongside DB writes.
Stripe integration points marked with # STRIPE_HOOK
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing import repository as repo
from app.modules.billing.models import TenantSubscription, TenantAddonSubscription
from app.modules.tenants.models import Tenant
from app.core.enums import TenantStatus, SubscriptionStatus


async def activate_subscription(
    db: AsyncSession,
    *,
    tenant: Tenant,
    plan_id: int,
    currency: str = "AUD",
    trial_days: int = 0,
    notes: str | None = None,
    # STRIPE_HOOK: stripe_subscription_id: str | None = None,
    # STRIPE_HOOK: stripe_customer_id: str | None = None,
) -> TenantSubscription:
    """
    Activates a plan for a tenant.
    Cancels any existing active subscription first.
    """
    now = datetime.now(timezone.utc)

    # Cancel existing
    existing = await repo.get_active_subscription(db, tenant_id=tenant.id)
    if existing:
        existing.status      = SubscriptionStatus.CANCELLED
        existing.cancelled_at = now
        # STRIPE_HOOK: await stripe.cancel_subscription(existing.stripe_subscription_id)

    sub_status = SubscriptionStatus.TRIALING if trial_days > 0 else SubscriptionStatus.ACTIVE

    sub = TenantSubscription(
        tenant_id            = tenant.id,
        plan_id              = plan_id,
        status               = sub_status,
        currency             = currency,
        current_period_start = now,
        current_period_end   = now + timedelta(days=30),
        trial_ends_at        = now + timedelta(days=trial_days) if trial_days > 0 else None,
        notes                = notes,
        # STRIPE_HOOK: stripe_subscription_id = stripe_subscription_id,
        # STRIPE_HOOK: stripe_customer_id     = stripe_customer_id,
    )
    db.add(sub)

    # Update tenant status
    tenant.status = TenantStatus.TRIAL if trial_days > 0 else TenantStatus.ACTIVE
    if trial_days > 0:
        tenant.trial_ends_at = now + timedelta(days=trial_days)

    await db.flush()
    await db.refresh(sub)
    return sub


async def cancel_subscription(
    db: AsyncSession,
    *,
    tenant: Tenant,
    immediately: bool = True,
    notes: str | None = None,
    # STRIPE_HOOK: at_period_end: bool = False,
) -> Optional[TenantSubscription]:
    sub = await repo.get_active_subscription(db, tenant_id=tenant.id)
    if not sub:
        return None

    now = datetime.now(timezone.utc)

    if immediately:
        sub.status       = SubscriptionStatus.CANCELLED
        sub.cancelled_at = now
        tenant.status    = TenantStatus.CANCELLED
        # STRIPE_HOOK: await stripe.cancel_subscription(sub.stripe_subscription_id, immediately=True)
    else:
        sub.cancel_at_period_end = True
        # STRIPE_HOOK: await stripe.update_subscription(sub.stripe_subscription_id, cancel_at_period_end=True)

    if notes:
        sub.notes = notes

    await db.flush()
    return sub


async def change_plan(
    db: AsyncSession,
    *,
    tenant: Tenant,
    new_plan_id: int,
    currency: str = "AUD",
    notes: str | None = None,
    # STRIPE_HOOK: new_stripe_price_id: str | None = None,
) -> TenantSubscription:
    sub = await repo.get_active_subscription(db, tenant_id=tenant.id)
    if not sub:
        return await activate_subscription(
            db, tenant=tenant, plan_id=new_plan_id,
            currency=currency, notes=notes,
        )

    sub.plan_id  = new_plan_id
    sub.currency = currency
    if notes:
        sub.notes = notes
    # STRIPE_HOOK: await stripe.update_subscription(sub.stripe_subscription_id, price_id=new_stripe_price_id)

    await db.flush()
    await db.refresh(sub)
    return sub


async def add_addon(
    db: AsyncSession,
    *,
    tenant_id: int,
    addon_id: int,
    subscription_id: int,
    quantity: int = 1,
    currency: str = "AUD",
    notes: str | None = None,
    # STRIPE_HOOK: stripe_subscription_item_id: str | None = None,
) -> TenantAddonSubscription:
    existing = await repo.get_tenant_addon(db, tenant_id=tenant_id, addon_id=addon_id)
    if existing:
        existing.quantity += quantity
        existing.status    = SubscriptionStatus.ACTIVE
        if notes:
            existing.notes = notes
        # STRIPE_HOOK: await stripe.update_subscription_item(existing.stripe_subscription_item_id, quantity=existing.quantity)
        await db.flush()
        return existing

    addon_sub = TenantAddonSubscription(
        tenant_id       = tenant_id,
        addon_id        = addon_id,
        subscription_id = subscription_id,
        quantity        = quantity,
        currency        = currency,
        notes           = notes,
        # STRIPE_HOOK: stripe_subscription_item_id = stripe_subscription_item_id,
    )
    db.add(addon_sub)
    await db.flush()
    await db.refresh(addon_sub)
    return addon_sub


async def mark_past_due(
    db: AsyncSession,
    *,
    tenant: Tenant,
    notes: str | None = None,
    # STRIPE_HOOK: stripe_invoice_id: str | None = None,
) -> Optional[TenantSubscription]:
    """
    Called when a payment attempt fails (Stripe invoice.payment_failed webhook).

    - Transitions subscription status → past_due (read-only mode).
    - Does NOT change tenant.status — Gate 1 stays green so the tenant
      can still log in and view their data. Gate 2 (is_read_only=True) is
      what blocks writes via the TenantContext dependency.
    - A follow-up job or Stripe webhook calls cancel_subscription() if
      payment is still overdue after the grace period.
    """
    sub = await repo.get_active_subscription(db, tenant_id=tenant.id)
    if not sub:
        return None

    sub.status = SubscriptionStatus.PAST_DUE
    if notes:
        sub.notes = notes
    # STRIPE_HOOK: log stripe_invoice_id for retry tracking

    await db.flush()
    return sub


async def mark_active(
    db: AsyncSession,
    *,
    tenant: Tenant,
    notes: str | None = None,
    # STRIPE_HOOK: stripe_invoice_id: str | None = None,
) -> Optional[TenantSubscription]:
    """
    Called when a previously failed payment succeeds (Stripe invoice.paid webhook).

    - Transitions subscription status past_due → active.
    - Restores tenant.status → active so Gate 1 passes cleanly.
    """
    sub = await repo.get_active_subscription(db, tenant_id=tenant.id)
    if not sub:
        return None

    sub.status    = SubscriptionStatus.ACTIVE
    tenant.status = TenantStatus.ACTIVE
    if notes:
        sub.notes = notes

    await db.flush()
    return sub


async def remove_addon(
    db: AsyncSession,
    *,
    tenant_id: int,
    addon_id: int,
    notes: str | None = None,
    # STRIPE_HOOK: cancel_on_stripe: bool = True,
) -> None:
    existing = await repo.get_tenant_addon(db, tenant_id=tenant_id, addon_id=addon_id)
    if existing:
        existing.status = SubscriptionStatus.CANCELLED
        if notes:
            existing.notes = notes
        # STRIPE_HOOK: await stripe.cancel_subscription_item(existing.stripe_subscription_item_id)
        await db.flush()