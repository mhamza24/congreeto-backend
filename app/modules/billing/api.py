# app/modules/billing/api.py
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse
from app.dependencies.auth import get_current_user
from app.core.enums import UsageMetric
from app.modules.billing import schemas, service

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/billing", tags=["Billing"])
DBDep  = Annotated[AsyncSession, Depends(get_db)]


# =============================================================================
# PUBLIC — no auth required
# =============================================================================

@router.get(
    "/plans",
    response_model=ApiResponse[list[schemas.PlanResponse]],
    summary="List available plans (public)",
)
async def list_plans(db: DBDep) -> ApiResponse[list[schemas.PlanResponse]]:
    """Shown on the plan selection page during onboarding."""
    result = await service.list_public_plans(db)
    return ApiResponse(success=True, message="Plans fetched.", data=result)


@router.get(
    "/addons",
    response_model=ApiResponse[list[schemas.AddonResponse]],
    summary="List available addons (public)",
)
async def list_addons(db: DBDep) -> ApiResponse[list[schemas.AddonResponse]]:
    result = await service.list_addons(db)
    return ApiResponse(success=True, message="Addons fetched.", data=result)


# =============================================================================
# TENANT — auth required
# =============================================================================

@router.get(
    "/tenants/{tenant_public_id}/billing",
    response_model=ApiResponse[schemas.TenantBillingOverview],
    summary="Get full billing overview for a tenant",
)
async def get_billing_overview(
    tenant_public_id: str,
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.TenantBillingOverview]:
    try:
        result = await service.get_tenant_billing_overview(
            db, tenant_public_id=tenant_public_id
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error fetching billing overview")
        raise HTTPException(status_code=500, detail="Could not fetch billing overview.")
    return ApiResponse(success=True, message="Billing overview fetched.", data=result)


@router.get(
    "/tenants/{tenant_public_id}/billing/limits/{metric}",
    response_model=ApiResponse[schemas.LimitCheckResponse],
    summary="Check a specific usage limit for a tenant",
)
async def check_limit(
    tenant_public_id: str,
    metric: UsageMetric,
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.LimitCheckResponse]:
    """
    Called by frontend before creating a conversation or uploading a document.
    allowed=False means the action should be blocked.
    """
    try:
        # resolve tenant_id from public_id
        from app.modules.tenants import repository as tenant_repo
        tenant = await tenant_repo.get_tenant_by_public_id(db, public_id=tenant_public_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")
        result = await service.check_limit(db, tenant_id=tenant.id, metric=metric)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error checking limit")
        raise HTTPException(status_code=500, detail="Could not check limit.")
    return ApiResponse(success=True, message="Limit checked.", data=result)


# =============================================================================
# ADMIN — plan management
# =============================================================================

@router.get(
    "/admin/plans",
    response_model=ApiResponse[list[schemas.PlanResponse]],
    summary="List all plans including hidden (admin only)",
)
async def admin_list_plans(
    db: DBDep,
    current_user=Depends(get_current_user),
    # TODO: swap → get_super_admin
) -> ApiResponse[list[schemas.PlanResponse]]:
    result = await service.list_all_plans(db)
    return ApiResponse(success=True, message="All plans fetched.", data=result)


@router.post(
    "/admin/plans",
    response_model=ApiResponse[schemas.PlanResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new plan (admin only)",
)
async def create_plan(
    payload: schemas.PlanCreateRequest,
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.PlanResponse]:
    try:
        result = await service.create_plan(db, payload=payload)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error creating plan")
        raise HTTPException(status_code=500, detail="Could not create plan.")
    return ApiResponse(success=True, message="Plan created.", data=result)


@router.patch(
    "/admin/plans/{plan_public_id}",
    response_model=ApiResponse[schemas.PlanResponse],
    summary="Update a plan (admin only)",
)
async def update_plan(
    plan_public_id: str,
    payload: schemas.PlanUpdateRequest,
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.PlanResponse]:
    try:
        result = await service.update_plan(
            db, plan_public_id=plan_public_id, payload=payload
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error updating plan")
        raise HTTPException(status_code=500, detail="Could not update plan.")
    return ApiResponse(success=True, message="Plan updated.", data=result)


# =============================================================================
# ADMIN — addon management
# =============================================================================

@router.post(
    "/admin/addons",
    response_model=ApiResponse[schemas.AddonResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new addon (admin only)",
)
async def create_addon(
    payload: schemas.AddonCreateRequest,
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.AddonResponse]:
    try:
        result = await service.create_addon(db, payload=payload)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error creating addon")
        raise HTTPException(status_code=500, detail="Could not create addon.")
    return ApiResponse(success=True, message="Addon created.", data=result)


# =============================================================================
# ADMIN — subscription management
# =============================================================================

@router.post(
    "/admin/tenants/{tenant_public_id}/billing/activate",
    response_model=ApiResponse[schemas.SubscriptionResponse],
    summary="Manually activate a subscription (admin only)",
)
async def activate_subscription(
    tenant_public_id: str,
    payload: schemas.ActivateSubscriptionRequest,
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.SubscriptionResponse]:
    """
    Admin calls this after receiving manual payment.
    Use notes to record: payment method, reference, amount, date.
    """
    try:
        result = await service.activate_subscription(
            db, tenant_public_id=tenant_public_id, payload=payload
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error activating subscription")
        raise HTTPException(status_code=500, detail="Could not activate subscription.")
    return ApiResponse(success=True, message="Subscription activated.", data=result)


@router.patch(
    "/admin/tenants/{tenant_public_id}/billing/plan",
    response_model=ApiResponse[schemas.SubscriptionResponse],
    summary="Change a tenant's plan (admin only)",
)
async def change_plan(
    tenant_public_id: str,
    payload: schemas.ChangePlanRequest,
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.SubscriptionResponse]:
    try:
        result = await service.change_plan(
            db, tenant_public_id=tenant_public_id, payload=payload
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error changing plan")
        raise HTTPException(status_code=500, detail="Could not change plan.")
    return ApiResponse(success=True, message="Plan changed.", data=result)


@router.post(
    "/admin/tenants/{tenant_public_id}/billing/cancel",
    response_model=ApiResponse[schemas.SubscriptionResponse],
    summary="Cancel a tenant's subscription (admin only)",
)
async def cancel_subscription(
    tenant_public_id: str,
    payload: schemas.CancelSubscriptionRequest,
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.SubscriptionResponse]:
    try:
        result = await service.cancel_subscription(
            db, tenant_public_id=tenant_public_id, payload=payload
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error cancelling subscription")
        raise HTTPException(status_code=500, detail="Could not cancel subscription.")
    return ApiResponse(success=True, message="Subscription cancelled.", data=result)


@router.post(
    "/admin/tenants/{tenant_public_id}/billing/addons",
    response_model=ApiResponse[schemas.TenantAddonResponse],
    summary="Add an addon to a tenant (admin only)",
)
async def add_addon(
    tenant_public_id: str,
    payload: schemas.AddAddonRequest,
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.TenantAddonResponse]:
    try:
        result = await service.add_addon(
            db, tenant_public_id=tenant_public_id, payload=payload
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error adding addon")
        raise HTTPException(status_code=500, detail="Could not add addon.")
    return ApiResponse(success=True, message="Addon added.", data=result)


@router.delete(
    "/admin/tenants/{tenant_public_id}/billing/addons",
    response_model=ApiResponse[dict],
    summary="Remove an addon from a tenant (admin only)",
)
async def remove_addon(
    tenant_public_id: str,
    payload: schemas.RemoveAddonRequest,
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[dict]:
    try:
        result = await service.remove_addon(
            db, tenant_public_id=tenant_public_id, payload=payload
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error removing addon")
        raise HTTPException(status_code=500, detail="Could not remove addon.")
    return ApiResponse(success=True, message="Addon removed.", data=result)