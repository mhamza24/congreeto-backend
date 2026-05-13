"""
app/modules/audit/api.py

Two audit log endpoints:
  GET /audit/admin/logs                — super admin: all tenants
  GET /audit/{tenant_public_id}/logs   — tenant admin: their own tenant only

Both use cursor (keyset) pagination — see app/core/pagination.py.
The legacy ?offset/?limit params are gone; clients pass ?cursor= instead.
"""
from __future__ import annotations

import logging
from typing import Annotated, List, Optional

import sentry_sdk
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.database import get_db
from app.core.pagination import CursorPage
from app.core.response import ApiResponse
from app.dependencies.auth import require_superadmin
from app.dependencies.tenant import TenantContext, get_tenant_context
from app.modules.audit import repository as audit_repo
from app.modules.audit.schemas import AuditLogResponse
from app.modules.tenants import repository as tenant_repo
from app.modules.users import repository as user_repo

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/audit", tags=["Audit Logs"])

DBDep = Annotated[AsyncSession, Depends(get_db)]


# =============================================================================
# SUPER ADMIN — all tenants
# =============================================================================

@router.get(
    "/admin/logs",
    response_model=ApiResponse[CursorPage[AuditLogResponse]],
    summary="List audit logs across all tenants (super admin only)",
)
async def admin_list_audit_logs(
    db: DBDep,
    current_user=Depends(require_superadmin),
    tenant_public_id: Optional[str] = Query(default=None, description="Filter by tenant public id"),
    user_public_id: Optional[str] = Query(default=None, description="Filter by user public id"),
    entity_type: Optional[str] = Query(default=None, description="e.g. 'tenants', 'listings'"),
    action: Optional[str] = Query(default=None, description="e.g. 'create', 'login'"),
    page_size: int = Query(
        default=settings.AUDIT_PAGE_SIZE_DEFAULT,
        ge=1, le=settings.AUDIT_PAGE_SIZE_MAX,
        description="Items per page.",
    ),
    cursor: Optional[str] = Query(default=None, description="Opaque cursor from previous response."),
) -> ApiResponse[CursorPage[AuditLogResponse]]:
    tenant_id: Optional[int] = None
    user_id: Optional[int] = None

    if tenant_public_id is not None:
        tenant = await tenant_repo.get_tenant_by_public_id(db, public_id=tenant_public_id)
        if tenant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
        tenant_id = tenant.id

    if user_public_id is not None:
        user = await user_repo.get_user_by_public_id(db, public_id=user_public_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        user_id = user.id

    page = await _fetch_page(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        entity_type=entity_type,
        action=action,
        page_size=page_size,
        cursor=cursor,
    )
    return ApiResponse(success=True, message="Audit logs fetched.", data=page)


# =============================================================================
# TENANT ADMIN — their tenant + members only
# =============================================================================

@router.get(
    "/{tenant_public_id}/logs",
    response_model=ApiResponse[CursorPage[AuditLogResponse]],
    summary="List audit logs for a specific tenant (tenant admin or super admin)",
)
async def tenant_list_audit_logs(
    db: DBDep,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    user_public_id: Optional[str] = Query(default=None, description="Filter by member user public id"),
    entity_type: Optional[str] = Query(default=None, description="e.g. 'listings', 'chatbot_configs'"),
    action: Optional[str] = Query(default=None, description="e.g. 'create', 'update'"),
    page_size: int = Query(
        default=settings.AUDIT_PAGE_SIZE_DEFAULT,
        ge=1, le=settings.AUDIT_PAGE_SIZE_MAX,
        description="Items per page.",
    ),
    cursor: Optional[str] = Query(default=None, description="Opaque cursor from previous response."),
) -> ApiResponse[CursorPage[AuditLogResponse]]:
    if not ctx.membership.is_owner_or_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tenant owners and admins can view audit logs.",
        )

    user_id: Optional[int] = None
    if user_public_id is not None:
        user = await user_repo.get_user_by_public_id(db, public_id=user_public_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        user_id = user.id

    page = await _fetch_page(
        db,
        tenant_id=ctx.tenant.id,
        user_id=user_id,
        entity_type=entity_type,
        action=action,
        page_size=page_size,
        cursor=cursor,
    )
    return ApiResponse(success=True, message="Audit logs fetched.", data=page)


# =============================================================================
# SHARED HELPER
# =============================================================================

async def _fetch_page(
    db: AsyncSession,
    *,
    tenant_id: Optional[int],
    user_id: Optional[int],
    entity_type: Optional[str],
    action: Optional[str],
    page_size: int,
    cursor: Optional[str],
) -> CursorPage[AuditLogResponse]:
    try:
        rows = await audit_repo.list_logs_keyset(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            entity_type=entity_type,
            action=action,
            page_size=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        # Bad cursor — give the client a clear 400 instead of leaking 500.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        logger.exception("audit fetch_page failed tenant_id=%s user_id=%s", tenant_id, user_id)
        raise HTTPException(status_code=500, detail="Could not fetch audit logs.")

    page = CursorPage.build(rows, page_size, sort_attr="created_at", id_attr="id")
    page.items = [AuditLogResponse.model_validate(item) for item in page.items]
    return page
