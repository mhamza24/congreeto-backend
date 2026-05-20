# app/modules/billing/service.py
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import stripe as stripe_sdk

logger = logging.getLogger(__name__)

from app.modules.audit import repository as audit

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing import repository as repo, contracts, schemas
from app.modules.billing.models import Plan, Addon
from app.modules.billing.task_helpers import (
    current_period_month,
    compute_limit_status,
    check_and_enforce_limit,
    can_start_new_conversation,
    can_continue_conversation,
)
from app.core.enums import UsageMetric, LimitStatus, SubscriptionStatus, BillingInterval
from app.modules.tenants.models import Tenant
from app.modules.tenants import repository as tenant_repo
from app.modules.tenants.repository import count_active_members
from app.config.settings import get_settings

settings = get_settings()

# Maps usage metric → (plan.limits key, fallback default).
# Defaults are sourced from Settings — keep all plan-level fallbacks
# in one place so they can be tuned without code edits.
METRIC_CONFIG: dict[UsageMetric, tuple[str, int]] = {
    UsageMetric.CONVERSATIONS:      ("max_conversations_per_month", settings.BILLING_DEFAULT_MAX_CONVERSATIONS_PER_MONTH),
    UsageMetric.TOKENS_USED:        ("max_tokens_per_month",        settings.BILLING_DEFAULT_MAX_TOKENS_PER_MONTH),
    UsageMetric.MESSAGES:           ("max_conversations_per_month", settings.BILLING_DEFAULT_MAX_CONVERSATIONS_PER_MONTH),
    UsageMetric.DOCUMENTS_UPLOADED: ("max_documents",               settings.BILLING_DEFAULT_MAX_DOCUMENTS),
    UsageMetric.PAGES_CRAWLED:      ("max_pages_crawled",           settings.BILLING_DEFAULT_MAX_PAGES_CRAWLED),
    UsageMetric.ACTIVE_USERS:       ("max_users",                   settings.DEFAULT_SEAT_LIMIT),
}


# =============================================================================
# STRIPE HELPERS  (admin plan sync only — checkout/webhooks live in stripe/)
# =============================================================================

def _stripe_ready() -> bool:
    key = settings.STRIPE_SECRET_KEY
    return bool(key) and key not in ("sk_test_REPLACE_ME", "sk_live_REPLACE_ME", "")


def _stripe_setup() -> None:
    stripe_sdk.api_key     = settings.STRIPE_SECRET_KEY
    stripe_sdk.api_version = settings.STRIPE_API_VERSION


def _stripe_interval(billing_interval: BillingInterval) -> str:
    return "month" if billing_interval == BillingInterval.MONTHLY else "year"


def _create_stripe_product_and_price(plan: Plan) -> None:
    """
    Create a Stripe Product + recurring Price for the plan.
    Writes the returned price id back onto the plan object in-memory.
    Caller is responsible for flush/commit.
    No-ops when Stripe is not configured or the USD price is 0.
    """
    if not _stripe_ready() or plan.price_usd_cents <= 0:
        return
    _stripe_setup()
    try:
        product = stripe_sdk.Product.create(
            name=plan.name,
            description=plan.description or "",
            metadata={"plan_slug": plan.slug, "plan_public_id": plan.public_id},
        )
        price = stripe_sdk.Price.create(
            product=product.id,
            unit_amount=plan.price_usd_cents,
            currency="usd",
            recurring={"interval": _stripe_interval(plan.billing_interval)},
            metadata={"plan_slug": plan.slug, "plan_public_id": plan.public_id},
        )
        if plan.billing_interval == BillingInterval.MONTHLY:
            plan.stripe_monthly_price_id = price.id
        else:
            plan.stripe_annual_price_id = price.id
        logger.info(
            "[billing] Stripe product+price created plan=%s product=%s price=%s",
            plan.slug, product.id, price.id,
        )
    except stripe_sdk.error.StripeError as exc:
        logger.warning("[billing] Stripe product/price creation failed plan=%s: %s", plan.slug, exc)


def _update_stripe_price(plan: Plan) -> None:
    """
    When a plan's USD price changes, create a new Stripe Price on the same
    Product and deactivate the old one (Stripe prices are immutable).
    If no price id exists yet, falls back to creating a new Product + Price.
    No-ops when Stripe is not configured or the new price is 0.
    """
    if not _stripe_ready() or plan.price_usd_cents <= 0:
        return
    _stripe_setup()
    is_monthly  = plan.billing_interval == BillingInterval.MONTHLY
    old_price_id = plan.stripe_monthly_price_id if is_monthly else plan.stripe_annual_price_id

    try:
        if old_price_id:
            old_price  = stripe_sdk.Price.retrieve(old_price_id)
            product_id = old_price.product
            new_price  = stripe_sdk.Price.create(
                product=product_id,
                unit_amount=plan.price_usd_cents,
                currency="usd",
                recurring={"interval": _stripe_interval(plan.billing_interval)},
                metadata={"plan_slug": plan.slug, "plan_public_id": plan.public_id},
            )
            stripe_sdk.Price.modify(old_price_id, active=False)
            if is_monthly:
                plan.stripe_monthly_price_id = new_price.id
            else:
                plan.stripe_annual_price_id = new_price.id
            logger.info(
                "[billing] Stripe price updated plan=%s old=%s new=%s",
                plan.slug, old_price_id, new_price.id,
            )
        else:
            _create_stripe_product_and_price(plan)
    except stripe_sdk.error.StripeError as exc:
        logger.warning("[billing] Stripe price update failed plan=%s: %s", plan.slug, exc)


# =============================================================================
# PLAN OPERATIONS
# =============================================================================

async def list_public_plans(db: AsyncSession) -> list[schemas.PlanResponse]:
    plans = await repo.list_public_plans(db)
    logger.debug("[billing] list_public_plans count=%d", len(plans))
    return [schemas.PlanResponse.from_plan(p) for p in plans]


async def list_all_plans(db: AsyncSession) -> list[schemas.PlanResponse]:
    plans = await repo.list_all_plans(db)
    logger.debug("[billing] list_all_plans count=%d", len(plans))
    return [schemas.PlanResponse.from_plan(p) for p in plans]


async def create_plan(
    db: AsyncSession, *, payload: schemas.PlanCreateRequest
) -> schemas.PlanResponse:
    if await repo.get_plan_by_slug(db, slug=payload.slug):
        logger.warning("[billing] create_plan conflict slug=%s", payload.slug)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Plan with slug '{payload.slug}' already exists.",
        )
    plan = Plan(
        name             = payload.name,
        slug             = payload.slug,
        description      = payload.description,
        billing_interval = payload.billing_interval,
        price_aud_cents  = payload.price_aud_cents,
        price_usd_cents  = payload.price_usd_cents,
        limits           = payload.limits.model_dump(),
        is_public        = payload.is_public,
        sort_order       = payload.sort_order,
    )
    plan = await repo.create_plan(db, plan=plan)
    _create_stripe_product_and_price(plan)

    await audit.write(
        db,
        entity_type="plans",
        action=audit.CREATE,
        entity_id=plan.id,
        diff={"after": {"slug": plan.slug, "name": plan.name, "billing_interval": str(plan.billing_interval)}},
    )

    await db.commit()
    logger.info("[billing] plan created slug=%s public_id=%s", plan.slug, plan.public_id)
    return schemas.PlanResponse.from_plan(plan)


async def sync_plan_to_stripe(
    db: AsyncSession, *, plan_public_id: str
) -> schemas.PlanResponse:
    plan = await _get_plan_or_404(db, public_id=plan_public_id)
    if not _stripe_ready():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stripe is not configured on this environment.",
        )
    if plan.price_usd_cents <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plan has no USD price set — cannot create a Stripe product.",
        )
    _create_stripe_product_and_price(plan)
    await db.commit()
    await db.refresh(plan)
    logger.info("[billing] plan synced to Stripe plan=%s price_id=%s/%s",
                plan.slug, plan.stripe_monthly_price_id, plan.stripe_annual_price_id)
    return schemas.PlanResponse.from_plan(plan)


async def update_plan(
    db: AsyncSession, *, plan_public_id: str, payload: schemas.PlanUpdateRequest
) -> schemas.PlanResponse:
    plan = await _get_plan_or_404(db, public_id=plan_public_id)
    changed = payload.model_dump(exclude_unset=True)
    changed_fields = list(changed.keys())

    old_price_usd_cents = plan.price_usd_cents

    for field, value in changed.items():
        if field == "limits" and value is not None:
            setattr(plan, field, value if isinstance(value, dict) else value.model_dump())
        else:
            setattr(plan, field, value)

    if "price_usd_cents" in changed and plan.price_usd_cents != old_price_usd_cents:
        _update_stripe_price(plan)

    await audit.write(
        db,
        entity_type="plans",
        action=audit.UPDATE,
        entity_id=plan.id,
        diff={"after": {k: str(v) for k, v in changed.items() if k != "limits"}},
    )

    await db.commit()
    await db.refresh(plan)
    logger.info("[billing] plan updated public_id=%s fields=%s", plan_public_id, changed_fields)
    return schemas.PlanResponse.from_plan(plan)


# =============================================================================
# USER-LEVEL BILLING
# =============================================================================

async def get_user_billing(
    db: AsyncSession,
    *,
    user_id: int,
) -> schemas.UserBillingResponse:
    """
    Returns the calling user's subscription status and tenant usage.
    Called immediately after login so the frontend knows whether to show
    the paywall or allow dashboard access.
    """
    sub = await repo.get_active_user_subscription(db, user_id=user_id)

    if sub:
        sub_response = schemas.UserSubscriptionResponse(
            public_id            = sub.public_id,
            status               = sub.status,
            currency             = sub.currency,
            plan                 = schemas.PlanResponse.from_plan(sub.plan),
            current_period_start = sub.current_period_start,
            current_period_end   = sub.current_period_end,
            trial_ends_at        = sub.trial_ends_at,
            cancelled_at         = sub.cancelled_at,
            cancel_at_period_end = sub.cancel_at_period_end,
            created_at           = sub.created_at,
        )
        max_tenants = sub.plan.get_limit("max_tenants", 1)
    else:
        sub_response = None
        max_tenants  = 0

    tenants_used = await tenant_repo.count_owned_tenants(db, user_id=user_id)

    return schemas.UserBillingResponse(
        subscription            = sub_response,
        has_active_subscription = bool(sub and sub.is_active),
        max_tenants             = max_tenants,
        tenants_used            = tenants_used,
    )


# =============================================================================
# ADMIN — USER SUBSCRIPTION MANAGEMENT
# =============================================================================

async def admin_activate_user_subscription(
    db: AsyncSession,
    *,
    user_public_id: str,
    payload: schemas.ActivateUserSubscriptionRequest,
) -> schemas.UserSubscriptionAdminResponse:
    """
    Admin manually activates or replaces a UserSubscription after receiving
    payment outside of Stripe (bank transfer, cash, etc.).
    Also used when a Stripe webhook was missed and the user is stuck.
    """
    from app.modules.users import repository as user_repo
    from app.modules.billing.models import UserSubscription
    from datetime import datetime, timezone, timedelta

    user = await user_repo.get_user_by_public_id(db, public_id=user_public_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    plan = await _get_plan_or_404(db, public_id=payload.plan_public_id)

    # Cancel any existing active subscription before creating a new one
    existing = await repo.get_active_user_subscription(db, user_id=user.id)
    if existing:
        existing.status       = SubscriptionStatus.CANCELLED
        existing.cancelled_at = datetime.now(timezone.utc)

    now   = datetime.now(timezone.utc)
    start = now
    end   = now + timedelta(days=payload.trial_days if payload.trial_days else 30)
    trial_ends_at = now + timedelta(days=payload.trial_days) if payload.trial_days else None
    sub_status    = SubscriptionStatus.TRIALING if payload.trial_days else SubscriptionStatus.ACTIVE

    sub = UserSubscription(
        user_id              = user.id,
        plan_id              = plan.id,
        status               = sub_status,
        currency             = payload.currency,
        current_period_start = start,
        current_period_end   = end,
        trial_ends_at        = trial_ends_at,
        notes                = payload.notes,
    )
    db.add(sub)

    await audit.write(
        db,
        entity_type="user_subscriptions",
        action=audit.ACTIVATE,
        entity_id=user.id,
        diff={"after": {
            "plan_slug": plan.slug,
            "status":    sub_status.value,
            "currency":  payload.currency,
            "source":    "admin_manual",
        }},
    )

    await db.commit()
    await db.refresh(sub)
    logger.info(
        "[billing] user subscription manually activated user=%s plan=%s",
        user_public_id, plan.slug,
    )
    return schemas.UserSubscriptionAdminResponse(
        public_id            = sub.public_id,
        status               = sub.status,
        currency             = sub.currency,
        plan                 = schemas.PlanResponse.from_plan(plan),
        current_period_start = sub.current_period_start,
        current_period_end   = sub.current_period_end,
        trial_ends_at        = sub.trial_ends_at,
        cancelled_at         = sub.cancelled_at,
        cancel_at_period_end = sub.cancel_at_period_end,
        notes                = sub.notes,
        created_at           = sub.created_at,
    )


# =============================================================================
# ADDON OPERATIONS
# =============================================================================

async def list_addons(db: AsyncSession) -> list[schemas.AddonResponse]:
    addons = await repo.list_active_addons(db)
    return [schemas.AddonResponse.from_addon(a) for a in addons]


async def create_addon(
    db: AsyncSession, *, payload: schemas.AddonCreateRequest
) -> schemas.AddonResponse:
    addon = Addon(
        name            = payload.name,
        slug            = payload.slug,
        description     = payload.description,
        type            = payload.type,
        price_aud_cents = payload.price_aud_cents,
        price_usd_cents = payload.price_usd_cents,
        config          = payload.config,
    )
    db.add(addon)
    await db.flush()
    await db.refresh(addon)

    await audit.write(
        db,
        entity_type="addons",
        action=audit.CREATE,
        entity_id=addon.id,
        diff={"after": {"slug": addon.slug, "name": addon.name, "type": str(addon.type)}},
    )

    await db.commit()
    logger.info("[billing] addon created slug=%s public_id=%s", addon.slug, addon.public_id)
    return schemas.AddonResponse.from_addon(addon)


# =============================================================================
# SUBSCRIPTION OPERATIONS
# =============================================================================

async def activate_subscription(
    db: AsyncSession, *, tenant_public_id: str,
    payload: schemas.ActivateSubscriptionRequest,
) -> schemas.SubscriptionResponse:
    logger.info("[billing] activating subscription tenant=%s plan=%s", tenant_public_id, payload.plan_public_id)
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    plan   = await _get_plan_or_404(db, public_id=payload.plan_public_id)
    sub    = await contracts.activate_subscription(
        db, tenant=tenant, plan_id=plan.id,
        currency=payload.currency, trial_days=payload.trial_days,
        notes=payload.notes,
    )

    await audit.write(
        db,
        entity_type="subscriptions",
        action=audit.ACTIVATE,
        tenant_id=tenant.id,
        entity_id=sub.id,
        diff={"after": {"plan_slug": plan.slug, "status": sub.status.value, "currency": sub.currency}},
    )

    await db.commit()
    logger.info("[billing] subscription activated tenant=%s plan=%s sub=%s", tenant_public_id, plan.slug, sub.public_id)
    return _build_subscription_response(sub, plan=plan)


async def change_plan(
    db: AsyncSession, *, tenant_public_id: str,
    payload: schemas.ChangePlanRequest,
) -> schemas.SubscriptionResponse:
    logger.info("[billing] changing plan tenant=%s new_plan=%s", tenant_public_id, payload.plan_public_id)
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    plan   = await _get_plan_or_404(db, public_id=payload.plan_public_id)
    sub    = await contracts.change_plan(
        db, tenant=tenant, new_plan_id=plan.id,
        currency=payload.currency, notes=payload.notes,
    )

    await audit.write(
        db,
        entity_type="subscriptions",
        action=audit.CHANGE_PLAN,
        tenant_id=tenant.id,
        entity_id=sub.id,
        diff={"after": {"plan_slug": plan.slug, "status": sub.status.value}},
    )

    await db.commit()
    logger.info("[billing] plan changed tenant=%s new_plan=%s sub=%s", tenant_public_id, plan.slug, sub.public_id)
    return _build_subscription_response(sub, plan=plan)


async def cancel_subscription(
    db: AsyncSession, *, tenant_public_id: str,
    payload: schemas.CancelSubscriptionRequest,
) -> schemas.SubscriptionResponse:
    logger.info("[billing] cancelling subscription tenant=%s immediately=%s", tenant_public_id, payload.immediately)
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    sub    = await contracts.cancel_subscription(
        db, tenant=tenant, immediately=payload.immediately, notes=payload.notes,
    )
    if not sub:
        logger.warning("[billing] cancel_subscription no active sub found tenant=%s", tenant_public_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found.",
        )

    await audit.write(
        db,
        entity_type="subscriptions",
        action=audit.CANCEL,
        tenant_id=tenant.id,
        entity_id=sub.id,
        diff={"after": {"status": sub.status.value, "immediately": payload.immediately}},
    )

    await db.commit()
    plan = await repo.get_plan_by_id(db, plan_id=sub.plan_id)
    logger.info("[billing] subscription cancelled tenant=%s sub=%s", tenant_public_id, sub.public_id)
    return _build_subscription_response(sub, plan=plan)


async def mark_past_due(
    db: AsyncSession, *, tenant_public_id: str, notes: str | None = None,
) -> schemas.SubscriptionResponse:
    logger.warning("[billing] marking subscription past_due tenant=%s", tenant_public_id)
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    sub = await repo.get_active_subscription(db, tenant_id=tenant.id)
    if not sub:
        logger.warning("[billing] mark_past_due no active sub found tenant=%s", tenant_public_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found.",
        )
    if sub.status == SubscriptionStatus.PAST_DUE:
        logger.warning("[billing] mark_past_due already past_due tenant=%s sub=%s", tenant_public_id, sub.public_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Subscription is already past_due.",
        )
    sub = await contracts.mark_past_due(db, tenant=tenant, notes=notes)

    await audit.write(
        db,
        entity_type="subscriptions",
        action=audit.UPDATE,
        tenant_id=tenant.id,
        entity_id=sub.id,
        diff={"before": {"status": "active"}, "after": {"status": "past_due"}},
    )

    await db.commit()
    plan = await repo.get_plan_by_id(db, plan_id=sub.plan_id)
    logger.info("[billing] subscription marked past_due tenant=%s sub=%s", tenant_public_id, sub.public_id)
    return _build_subscription_response(sub, plan=plan)


async def mark_active(
    db: AsyncSession, *, tenant_public_id: str, notes: str | None = None,
) -> schemas.SubscriptionResponse:
    logger.info("[billing] restoring subscription to active tenant=%s", tenant_public_id)
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    sub = await repo.get_active_subscription(db, tenant_id=tenant.id)
    if not sub:
        logger.warning("[billing] mark_active no sub found tenant=%s", tenant_public_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No subscription found.",
        )
    if sub.status != SubscriptionStatus.PAST_DUE:
        logger.warning("[billing] mark_active sub not past_due tenant=%s status=%s", tenant_public_id, sub.status.value)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot mark active — subscription is currently '{sub.status.value}', not past_due.",
        )
    sub = await contracts.mark_active(db, tenant=tenant, notes=notes)

    await audit.write(
        db,
        entity_type="subscriptions",
        action=audit.UPDATE,
        tenant_id=tenant.id,
        entity_id=sub.id,
        diff={"before": {"status": "past_due"}, "after": {"status": "active"}},
    )

    await db.commit()
    plan = await repo.get_plan_by_id(db, plan_id=sub.plan_id)
    logger.info("[billing] subscription restored to active tenant=%s sub=%s", tenant_public_id, sub.public_id)
    return _build_subscription_response(sub, plan=plan)


async def add_addon(
    db: AsyncSession, *, tenant_public_id: str,
    payload: schemas.AddAddonRequest,
) -> schemas.TenantAddonResponse:
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    addon  = await repo.get_addon_by_public_id(db, public_id=payload.addon_public_id)
    if not addon:
        logger.warning("[billing] add_addon not found addon=%s tenant=%s", payload.addon_public_id, tenant_public_id)
        raise HTTPException(status_code=404, detail="Addon not found.")
    if not addon.is_active:
        logger.warning("[billing] add_addon inactive addon=%s tenant=%s", addon.slug, tenant_public_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This addon is no longer available.",
        )
    sub = await repo.get_active_subscription(db, tenant_id=tenant.id)
    if not sub:
        logger.warning("[billing] add_addon no active subscription tenant=%s", tenant_public_id)
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Activate a plan before adding addons.",
        )
    addon_sub = await contracts.add_addon(
        db, tenant_id=tenant.id, addon_id=addon.id,
        subscription_id=sub.id, quantity=payload.quantity,
        currency=payload.currency, notes=payload.notes,
    )

    await audit.write(
        db,
        entity_type="tenant_addons",
        action=audit.CREATE,
        tenant_id=tenant.id,
        entity_id=addon_sub.id,
        diff={"after": {"addon_slug": addon.slug, "quantity": payload.quantity}},
    )

    await db.commit()
    logger.info("[billing] addon added tenant=%s addon=%s qty=%s", tenant_public_id, addon.slug, payload.quantity)
    return _build_addon_response(addon_sub, addon=addon)


async def remove_addon(
    db: AsyncSession, *, tenant_public_id: str,
    payload: schemas.RemoveAddonRequest,
) -> dict:
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    addon  = await repo.get_addon_by_public_id(db, public_id=payload.addon_public_id)
    if not addon:
        logger.warning("[billing] remove_addon not found addon=%s tenant=%s", payload.addon_public_id, tenant_public_id)
        raise HTTPException(status_code=404, detail="Addon not found.")
    existing = await repo.get_tenant_addon(db, tenant_id=tenant.id, addon_id=addon.id)
    if not existing:
        logger.warning("[billing] remove_addon not assigned addon=%s tenant=%s", addon.slug, tenant_public_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This addon is not assigned to the tenant.",
        )
    if existing.status == SubscriptionStatus.CANCELLED:
        logger.warning("[billing] remove_addon already cancelled addon=%s tenant=%s", addon.slug, tenant_public_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This addon is already cancelled.",
        )
    if payload.quantity is not None and payload.quantity > existing.quantity:
        logger.warning("[billing] remove_addon qty exceeds owned addon=%s requested=%s owned=%s", addon.slug, payload.quantity, existing.quantity)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot remove {payload.quantity} units — tenant only has {existing.quantity}.",
        )
    await audit.write(
        db,
        entity_type="tenant_addons",
        action=audit.DELETE,
        tenant_id=tenant.id,
        entity_id=existing.id,
        diff={"before": {"addon_slug": addon.slug, "quantity": payload.quantity or existing.quantity}},
    )

    await contracts.remove_addon(
        db, tenant_id=tenant.id, addon_id=addon.id,
        quantity=payload.quantity, notes=payload.notes,
    )
    await db.commit()
    logger.info("[billing] addon removed tenant=%s addon=%s qty=%s", tenant_public_id, addon.slug, payload.quantity)
    return {"message": "Addon removed successfully."}


# =============================================================================
# USAGE + LIMIT OPERATIONS
# =============================================================================

async def check_limit(
    db: AsyncSession, *, tenant_id: int, metric: UsageMetric,
) -> schemas.LimitCheckResponse:
    """
    Called by other modules before creating a resource.
    e.g. conversation module calls this before starting a new session.
    """
    metric_key, default = METRIC_CONFIG.get(metric, ("", 0))
    used, limit, lim_status = await check_and_enforce_limit(
        db, tenant_id=tenant_id, metric=metric,
        metric_key=metric_key, default_limit=default,
    )
    pct     = round((used / limit * 100), 2) if limit > 0 else 100.0
    allowed = lim_status != LimitStatus.EXCEEDED

    if not allowed:
        logger.warning("[billing] limit exceeded metric=%s used=%d limit=%d", metric, used, limit)
    elif pct >= 80:
        logger.info("[billing] limit approaching metric=%s used=%d limit=%d pct=%.1f%%", metric, used, limit, pct)

    return schemas.LimitCheckResponse(
        metric=metric, used=used, limit=limit,
        percentage=pct, status=lim_status, allowed=allowed,
    )


async def get_tenant_billing_overview(
    db: AsyncSession, *, tenant_public_id: str,
) -> schemas.TenantBillingOverview:
    tenant     = await _get_tenant_or_404(db, public_id=tenant_public_id)
    period     = current_period_month()
    sub        = await repo.get_active_subscription(db, tenant_id=tenant.id)
    addon_subs = await repo.list_tenant_addons(db, tenant_id=tenant.id)
    usage_recs = await repo.get_all_usage_for_period(
        db, tenant_id=tenant.id, period_month=period
    )

    # Build per-metric usage details
    metrics = []
    for record in usage_recs:
        metric_key, default = METRIC_CONFIG.get(record.metric, ("", 0))
        limit = 0
        if sub and metric_key:
            addon_grant = await repo.get_addon_grant_total(
                db, tenant_id=tenant.id, metric=metric_key
            )
            limit = sub.plan.get_limit(metric_key, default) + addon_grant

        pct    = round((record.quantity / limit * 100), 2) if limit > 0 else 0.0
        status = compute_limit_status(record.quantity, limit)

        metrics.append(schemas.UsageMetricDetail(
            metric     = record.metric,
            used       = record.quantity,
            limit      = limit,
            percentage = pct,
            status     = status,
            warned_80  = record.warned_80,
            warned_90  = record.warned_90,
        ))

    # Seat info
    seats_used  = await count_active_members(db, tenant_id=tenant.id)
    addon_seats = await repo.get_addon_grant_total(
        db, tenant_id=tenant.id, metric="max_users"
    )
    seats_total = (
        sub.plan.get_limit("max_users", settings.DEFAULT_SEAT_LIMIT) + addon_seats
        if sub else settings.DEFAULT_SEAT_LIMIT
    )

    return schemas.TenantBillingOverview(
        subscription    = _build_subscription_response(sub) if sub else None,
        addons          = [_build_addon_response(a) for a in addon_subs],
        usage           = schemas.TenantUsageSummary(
            period_month=period, metrics=metrics
        ),
        seats_used      = seats_used,
        seats_total     = seats_total,
        seats_remaining = max(0, seats_total - seats_used),
    )


# =============================================================================
# PRIVATE HELPERS
# =============================================================================

async def _get_tenant_or_404(db: AsyncSession, *, public_id: str) -> Tenant:
    tenant = await tenant_repo.get_tenant_by_public_id(db, public_id=public_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    return tenant


async def _get_plan_or_404(db: AsyncSession, *, public_id: str) -> Plan:
    plan = await repo.get_plan_by_public_id(db, public_id=public_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found.")
    return plan


def _build_subscription_response(sub, plan: Plan | None = None) -> schemas.SubscriptionResponse:
    return schemas.SubscriptionResponse(
        public_id            = sub.public_id,
        status               = sub.status,
        currency             = sub.currency,
        plan                 = schemas.PlanResponse.from_plan(plan or sub.plan),
        current_period_start = sub.current_period_start,
        current_period_end   = sub.current_period_end,
        trial_ends_at        = sub.trial_ends_at,
        cancelled_at         = sub.cancelled_at,
        cancel_at_period_end = sub.cancel_at_period_end,
        notes                = sub.notes,
        created_at           = sub.created_at,
    )


def _build_addon_response(addon_sub, addon=None) -> schemas.TenantAddonResponse:
    return schemas.TenantAddonResponse(
        public_id = addon_sub.public_id,
        addon     = schemas.AddonResponse.from_addon(addon or addon_sub.addon),
        quantity  = addon_sub.quantity,
        status    = addon_sub.status,
        currency  = addon_sub.currency,
        notes     = addon_sub.notes,
    )