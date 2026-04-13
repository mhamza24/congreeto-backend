from typing import Annotated, Optional

import sentry_sdk
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse, PagedApiResponse, PaginationMeta
from app.dependencies.auth import require_superadmin
from app.modules.dashboard import schemas, service

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

DBDep = Annotated[AsyncSession, Depends(get_db)]


# ── Tenant dashboard (existing) ────────────────────────────────────────────────

async def _get_tenant_id(tenant_id: str | None = Query(default=None)) -> str:
    return tenant_id or "veloce"

TenantDep = Annotated[str, Depends(_get_tenant_id)]


@router.get(
    "/summary",
    response_model=ApiResponse[schemas.DashboardSummaryResponse],
    status_code=status.HTTP_200_OK,
)
async def get_summary(db: DBDep, tenant_id: TenantDep):
    try:
        result = await service.fetch_summary(db, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        logger.exception("Unexpected error in dashboard summary endpoint")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch dashboard summary. Please try again later.",
        )
    return ApiResponse(success=True, message="Dashboard summary fetched successfully.", data=result)


# ── Super-admin analytics ──────────────────────────────────────────────────────

@router.get(
    "/admin/overview",
    response_model=ApiResponse[schemas.AdminOverviewResponse],
    summary="Platform-wide KPIs — tenants, revenue, leads, chatbots (super admin only)",
)
async def admin_overview(
    db: DBDep,
    _=Depends(require_superadmin),
):
    try:
        result = await service.fetch_admin_overview(db)
    except Exception:
        logger.exception("Unexpected error in admin overview endpoint")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch admin overview.",
        )
    return ApiResponse(success=True, message="Admin overview fetched successfully.", data=result)


@router.get(
    "/admin/tenants",
    response_model=PagedApiResponse[list[schemas.TenantRow]],
    summary="Paginated tenant table with plan and usage stats (super admin only)",
)
async def admin_tenants(
    db: DBDep,
    _=Depends(require_superadmin),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    try:
        result = await service.fetch_admin_tenants(db, limit=limit, offset=offset)
    except Exception:
        logger.exception("Unexpected error in admin tenants endpoint")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch tenants.",
        )
    return PagedApiResponse(
        success=True,
        message=f"{result.total} tenant(s) found.",
        data=result.tenants,
        meta=PaginationMeta(
            total=result.total,
            limit=limit,
            offset=offset,
            has_next=offset + limit < result.total,
            has_prev=offset > 0,
        ),
    )
