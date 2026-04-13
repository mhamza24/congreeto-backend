"""
app/modules/audit/api.py

Two audit log endpoints:
  GET /audit/admin/logs                        — super admin: all tenants
  GET /audit/{tenant_public_id}/logs     — tenant admin: their own tenant only

Both use the project-standard PagedApiResponse + PaginationMeta pattern.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated, List, Optional

import sentry_sdk
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import PagedApiResponse, PaginationMeta
from app.dependencies.auth import require_superadmin
from app.dependencies.tenant import TenantContext, get_tenant_context
from app.modules.audit import repository as audit_repo
from app.modules.audit.schemas import AuditLogResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["Audit Logs"])

DBDep = Annotated[AsyncSession, Depends(get_db)]


# =============================================================================
# SUPER ADMIN — all tenants
# =============================================================================

@router.get(
    "/admin/logs",
    response_model=PagedApiResponse[List[AuditLogResponse]],
    summary="List all audit logs across all tenants (super admin only)",
)
async def admin_list_audit_logs(
    db: DBDep,
    current_user=Depends(require_superadmin),
    tenant_id: Optional[int] = Query(default=None, description="Filter by tenant DB id"),
    user_id: Optional[int] = Query(default=None, description="Filter by user DB id"),
    entity_type: Optional[str] = Query(default=None, description="e.g. 'tenants', 'listings'"),
    action: Optional[str] = Query(default=None, description="e.g. 'create', 'login'"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> PagedApiResponse[List[AuditLogResponse]]:
    try:
        logs, total = await _fetch(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            entity_type=entity_type,
            action=action,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        logger.exception("admin_list_audit_logs failed")
        raise HTTPException(status_code=500, detail="Could not fetch audit logs.")

    return PagedApiResponse(
        success=True,
        message=f"{total} audit log(s) found.",
        data=logs,
        meta=PaginationMeta(
            total=total,
            limit=limit,
            offset=offset,
            has_next=offset + limit < total,
            has_prev=offset > 0,
        ),
    )


# =============================================================================
# TENANT ADMIN — their tenant + members only
# =============================================================================

@router.get(
    "/{tenant_public_id}/logs",
    response_model=PagedApiResponse[List[AuditLogResponse]],
    summary="List audit logs for a specific tenant (tenant admin or super admin)",
)
async def tenant_list_audit_logs(
    db: DBDep,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    user_id: Optional[int] = Query(default=None, description="Filter by member user id"),
    entity_type: Optional[str] = Query(default=None, description="e.g. 'listings', 'chatbot_configs'"),
    action: Optional[str] = Query(default=None, description="e.g. 'create', 'update'"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> PagedApiResponse[List[AuditLogResponse]]:
    if not ctx.membership.is_owner_or_admin:
        raise HTTPException(
            status_code=403,
            detail="Only tenant owners and admins can view audit logs.",
        )
    try:
        logs, total = await _fetch(
            db,
            tenant_id=ctx.tenant.id,
            user_id=user_id,
            entity_type=entity_type,
            action=action,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        logger.exception("tenant_list_audit_logs failed tenant=%s", ctx.tenant.public_id)
        raise HTTPException(status_code=500, detail="Could not fetch audit logs.")

    return PagedApiResponse(
        success=True,
        message=f"{total} audit log(s) found.",
        data=logs,
        meta=PaginationMeta(
            total=total,
            limit=limit,
            offset=offset,
            has_next=offset + limit < total,
            has_prev=offset > 0,
        ),
    )


# =============================================================================
# SHARED HELPER
# =============================================================================

async def _fetch(
    db: AsyncSession,
    *,
    tenant_id: Optional[int],
    user_id: Optional[int],
    entity_type: Optional[str],
    action: Optional[str],
    limit: int,
    offset: int,
) -> tuple[List[AuditLogResponse], int]:
    logs_raw, total = await asyncio.gather(
        audit_repo.list_logs(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            entity_type=entity_type,
            action=action,
            limit=limit,
            offset=offset,
        ),
        audit_repo.count_logs(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            entity_type=entity_type,
            action=action,
        ),
    )
    return [AuditLogResponse.model_validate(log) for log in logs_raw], total
