from typing import Annotated, Optional
from fastapi.responses import StreamingResponse
import io
import sentry_sdk
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.database import get_db
from app.core.pagination import CursorPage
from app.core.response import ApiResponse
from app.dependencies.auth import require_superadmin
from app.dependencies.tenant import TenantContext, get_tenant_context
from app.modules.dashboard import schemas, service

settings = get_settings()

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

DBDep  = Annotated[AsyncSession, Depends(get_db)]
CtxDep = Annotated[TenantContext, Depends(get_tenant_context)]


# ── Tenant: summary ───────────────────────────────────────────────────────────

@router.get(
    "/{tenant_public_id}/summary",
    response_model=ApiResponse[schemas.DashboardSummaryResponse],
    summary="Tenant chatbot dashboard summary",
)
async def get_summary(
    tenant_public_id: str,
    db: DBDep,
    ctx: CtxDep,
):
    try:
        result = await service.fetch_summary(db, tenant_id=str(ctx.tenant.id))
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


# ── Tenant: leads list ────────────────────────────────────────────────────────

@router.get(
    "/{tenant_public_id}/leads",
    response_model=ApiResponse[CursorPage[schemas.LeadListItem]],
    status_code=status.HTTP_200_OK,
    summary="List leads (cursor paginated)",
)
async def list_leads(
    tenant_public_id: str,
    db: DBDep,
    ctx: CtxDep,
    page_size: int = Query(
        default=settings.DASHBOARD_LEADS_PAGE_SIZE_DEFAULT,
        ge=1, le=settings.DASHBOARD_LEADS_PAGE_SIZE_MAX,
        description="Items per page.",
    ),
    cursor: Optional[str] = Query(default=None, description="Opaque cursor from previous response."),
):
    try:
        result = await service.fetch_leads(
            db,
            tenant_id=str(ctx.tenant.id),
            page_size=page_size,
            cursor=cursor,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        logger.exception("Unexpected error in list_leads")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch leads. Please try again later.",
        )
    return ApiResponse(success=True, message="Leads fetched successfully.", data=result)


# ── Tenant: lead detail ───────────────────────────────────────────────────────

@router.get(
    "/{tenant_public_id}/leads/{public_id}",
    response_model=ApiResponse[schemas.LeadDetailResponse],
    status_code=status.HTTP_200_OK,
    summary="Get full details of a single lead/conversation",
)
async def get_lead_detail(
    tenant_public_id: str,
    public_id: str,
    db: DBDep,
    ctx: CtxDep,
):
    try:
        result = await service.fetch_lead_detail(
            db,
            tenant_id=str(ctx.tenant.id),
            public_id=public_id,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error in get_lead_detail for %s", public_id)
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch lead details. Please try again later.",
        )
    return ApiResponse(success=True, message="Lead detail fetched successfully.", data=result)


# ── Tenant: export leads ──────────────────────────────────────────────────────

@router.get(
    "/{tenant_public_id}/leads/export/download",
    summary="Export leads to CSV or XLSX",
)
async def export_leads(
    tenant_public_id: str,
    db: DBDep,
    ctx: CtxDep,
    format: str = Query(default="xlsx", pattern="^(csv|xlsx)$", description="Export format: 'csv' or 'xlsx'"),
    last_days: Optional[int] = Query(default=None, ge=1, description="Export last N days"),
    date_from: Optional[str] = Query(default=None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(default=None, description="End date (YYYY-MM-DD)"),
):
    tenant_id = str(ctx.tenant.id)
    try:
        if format == "csv":
            file_bytes = await service.export_leads_csv(
                db, tenant_id=tenant_id, date_from=date_from, date_to=date_to, last_days=last_days
            )
            filename = f"leads_export_{tenant_public_id}.csv"
            media_type = "text/csv"
        else:
            file_bytes = await service.export_leads_xlsx(
                db, tenant_id=tenant_id, date_from=date_from, date_to=date_to, last_days=last_days
            )
            filename = f"leads_export_{tenant_public_id}.xlsx"
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    except Exception as exc:
        logger.exception("Unexpected error in export_leads")
        sentry_sdk.capture_exception(exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate export file. Please try again later.",
        )
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(file_bytes)),
        },
    )


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
    response_model=ApiResponse[CursorPage[schemas.TenantRow]],
    summary="Tenant table with plan and usage stats (cursor paginated, super admin only)",
)
async def admin_tenants(
    db: DBDep,
    _=Depends(require_superadmin),
    page_size: int = Query(
        default=settings.DASHBOARD_TENANTS_PAGE_SIZE_DEFAULT,
        ge=1, le=settings.DASHBOARD_TENANTS_PAGE_SIZE_MAX,
        description="Items per page.",
    ),
    cursor: Optional[str] = Query(default=None, description="Opaque cursor from previous response."),
):
    try:
        result = await service.fetch_admin_tenants(db, page_size=page_size, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        logger.exception("Unexpected error in admin tenants endpoint")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch tenants.",
        )
    return ApiResponse(success=True, message="Tenants fetched successfully.", data=result)
