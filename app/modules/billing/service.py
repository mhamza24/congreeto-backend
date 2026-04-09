# app/modules/billing/service.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

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
from app.core.enums import UsageMetric, LimitStatus
from app.modules.tenants.models import Tenant
from app.modules.tenants import repository as tenant_repo
from app.modules.tenants.repository import count_active_members
from app.config.settings import get_settings

settings = get_settings()

# Maps usage metric → plan limits key → default value
METRIC_CONFIG: dict[UsageMetric, tuple[str, int]] = {
    UsageMetric.CONVERSATIONS:      ("max_conversations_per_month", 750),
    UsageMetric.TOKENS_USED:        ("max_tokens_per_month",        1_000_000),
    UsageMetric.MESSAGES:           ("max_conversations_per_month", 750),
    UsageMetric.DOCUMENTS_UPLOADED: ("max_documents",               120),
    UsageMetric.PAGES_CRAWLED:      ("max_pages_crawled",           50),
    UsageMetric.ACTIVE_USERS:       ("max_users",                   settings.DEFAULT_SEAT_LIMIT),
}


# =============================================================================
# PLAN OPERATIONS
# =============================================================================

async def list_public_plans(db: AsyncSession) -> list[schemas.PlanResponse]:
    plans = await repo.list_public_plans(db)
    return [schemas.PlanResponse.from_plan(p) for p in plans]


async def list_all_plans(db: AsyncSession) -> list[schemas.PlanResponse]:
    plans = await repo.list_all_plans(db)
    return [schemas.PlanResponse.from_plan(p) for p in plans]


async def create_plan(
    db: AsyncSession, *, payload: schemas.PlanCreateRequest
) -> schemas.PlanResponse:
    if await repo.get_plan_by_slug(db, slug=payload.slug):
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
    await db.commit()
    return schemas.PlanResponse.from_plan(plan)


async def update_plan(
    db: AsyncSession, *, plan_public_id: str, payload: schemas.PlanUpdateRequest
) -> schemas.PlanResponse:
    plan = await _get_plan_or_404(db, public_id=plan_public_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "limits" and value is not None:
            setattr(plan, field, value if isinstance(value, dict) else value.model_dump())
        else:
            setattr(plan, field, value)
    await db.commit()
    await db.refresh(plan)
    return schemas.PlanResponse.from_plan(plan)


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
    await db.commit()
    return schemas.AddonResponse.from_addon(addon)


# =============================================================================
# SUBSCRIPTION OPERATIONS
# =============================================================================

async def activate_subscription(
    db: AsyncSession, *, tenant_public_id: str,
    payload: schemas.ActivateSubscriptionRequest,
) -> schemas.SubscriptionResponse:
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    plan   = await _get_plan_or_404(db, public_id=payload.plan_public_id)
    sub    = await contracts.activate_subscription(
        db, tenant=tenant, plan_id=plan.id,
        currency=payload.currency, trial_days=payload.trial_days,
        notes=payload.notes,
    )
    await db.commit()
    await db.refresh(sub)
    return _build_subscription_response(sub)


async def change_plan(
    db: AsyncSession, *, tenant_public_id: str,
    payload: schemas.ChangePlanRequest,
) -> schemas.SubscriptionResponse:
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    plan   = await _get_plan_or_404(db, public_id=payload.plan_public_id)
    sub    = await contracts.change_plan(
        db, tenant=tenant, new_plan_id=plan.id,
        currency=payload.currency, notes=payload.notes,
    )
    await db.commit()
    await db.refresh(sub)
    return _build_subscription_response(sub)


async def cancel_subscription(
    db: AsyncSession, *, tenant_public_id: str,
    payload: schemas.CancelSubscriptionRequest,
) -> schemas.SubscriptionResponse:
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    sub    = await contracts.cancel_subscription(
        db, tenant=tenant, immediately=payload.immediately, notes=payload.notes,
    )
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found.",
        )
    await db.commit()
    await db.refresh(sub)
    return _build_subscription_response(sub)


async def mark_past_due(
    db: AsyncSession, *, tenant_public_id: str, notes: str | None = None,
) -> schemas.SubscriptionResponse:
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    sub = await contracts.mark_past_due(db, tenant=tenant, notes=notes)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found.",
        )
    await db.commit()
    await db.refresh(sub)
    return _build_subscription_response(sub)


async def mark_active(
    db: AsyncSession, *, tenant_public_id: str, notes: str | None = None,
) -> schemas.SubscriptionResponse:
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    sub = await contracts.mark_active(db, tenant=tenant, notes=notes)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found.",
        )
    await db.commit()
    await db.refresh(sub)
    return _build_subscription_response(sub)


async def add_addon(
    db: AsyncSession, *, tenant_public_id: str,
    payload: schemas.AddAddonRequest,
) -> schemas.TenantAddonResponse:
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    addon  = await repo.get_addon_by_public_id(db, public_id=payload.addon_public_id)
    if not addon:
        raise HTTPException(status_code=404, detail="Addon not found.")
    sub = await repo.get_active_subscription(db, tenant_id=tenant.id)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Activate a plan before adding addons.",
        )
    addon_sub = await contracts.add_addon(
        db, tenant_id=tenant.id, addon_id=addon.id,
        subscription_id=sub.id, quantity=payload.quantity,
        currency=payload.currency, notes=payload.notes,
    )
    await db.commit()
    await db.refresh(addon_sub)
    return _build_addon_response(addon_sub)


async def remove_addon(
    db: AsyncSession, *, tenant_public_id: str,
    payload: schemas.RemoveAddonRequest,
) -> dict:
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    addon  = await repo.get_addon_by_public_id(db, public_id=payload.addon_public_id)
    if not addon:
        raise HTTPException(status_code=404, detail="Addon not found.")
    await contracts.remove_addon(
        db, tenant_id=tenant.id, addon_id=addon.id, notes=payload.notes,
    )
    await db.commit()
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


def _build_subscription_response(sub) -> schemas.SubscriptionResponse:
    return schemas.SubscriptionResponse(
        public_id            = sub.public_id,
        status               = sub.status,
        currency             = sub.currency,
        plan                 = schemas.PlanResponse.from_plan(sub.plan),
        current_period_start = sub.current_period_start,
        current_period_end   = sub.current_period_end,
        trial_ends_at        = sub.trial_ends_at,
        cancelled_at         = sub.cancelled_at,
        cancel_at_period_end = sub.cancel_at_period_end,
        notes                = sub.notes,
        created_at           = sub.created_at,
    )


def _build_addon_response(addon_sub) -> schemas.TenantAddonResponse:
    return schemas.TenantAddonResponse(
        public_id = addon_sub.public_id,
        addon     = schemas.AddonResponse.from_addon(addon_sub.addon),
        quantity  = addon_sub.quantity,
        status    = addon_sub.status,
        currency  = addon_sub.currency,
        notes     = addon_sub.notes,
    )