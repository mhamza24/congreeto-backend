"""
app/modules/audit/repository.py

Single responsibility: write to the audit_logs table.
All writes are INSERT-only.  Never UPDATE or DELETE.

Usage — inline (for low-frequency, security-critical actions):
    await audit.write(
        db,
        tenant_id=tenant.id,
        user_id=current_user.id,
        entity_type="tenants",
        entity_id=tenant.id,
        action="suspend",
        diff={"before": {"status": "active"}, "after": {"status": "suspended"}},
        request=request,          # FastAPI Request object — extracts IP + UA automatically
    )
    # The caller commits the outer transaction; audit row lands in the same commit.

Usage — fire-and-forget via Celery (for high-frequency or background paths):
    from app.modules.audit import tasks as audit_tasks
    audit_tasks.write_audit_log.delay(
        tenant_id=..., action="crawl_completed", entity_type="crawl_jobs", ...
    )
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog

logger = logging.getLogger(__name__)

# ── Public audit actions ───────────────────────────────────────────────────────
# Keep these consistent so Sentry/search/dashboards can filter by action name.

CREATE   = "create"
UPDATE   = "update"
DELETE   = "delete"
SUSPEND  = "suspend"
RESTORE  = "restore"
LOGIN    = "login"
LOGOUT   = "logout"
INVITE   = "invite"
EXPORT   = "export"


async def write(
    db: AsyncSession,
    *,
    entity_type: str,
    action: str,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    entity_id: Optional[int] = None,
    diff: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> AuditLog:
    """
    Append one row to audit_logs within the caller's existing DB session.

    The caller is responsible for the surrounding commit — this function only
    calls db.add() + db.flush() so the row lands in the same transaction as
    the business change it records.

    Args:
        db:          The active async session (shared with the business operation).
        entity_type: Table name being acted on, e.g. "tenants", "listings".
        action:      Verb describing the event (use the constants above).
        tenant_id:   NULL for platform-level actions.
        user_id:     NULL for system-triggered actions.
        entity_id:   PK of the affected row (NULL for bulk actions).
        diff:        {"before": {...}, "after": {...}} — omit fields that didn't change.
        request:     FastAPI Request — auto-extracts IP + User-Agent if provided.
        ip_address:  Explicit override (used when request is not available).
        user_agent:  Explicit override.

    Returns:
        The flushed (but not yet committed) AuditLog row.
    """
    # Resolve IP and UA from the request object when available
    if request is not None:
        if ip_address is None:
            forwarded = request.headers.get("x-forwarded-for")
            ip_address = forwarded.split(",")[0].strip() if forwarded else request.client.host if request.client else None
        if user_agent is None:
            user_agent = request.headers.get("user-agent")

    row = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        diff=diff or {},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(row)
    await db.flush()

    logger.debug(
        "audit: %s %s:%s by user=%s tenant=%s",
        action,
        entity_type,
        entity_id,
        user_id,
        tenant_id,
    )
    return row


async def write_system(
    db: AsyncSession,
    *,
    entity_type: str,
    action: str,
    entity_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
    diff: Optional[dict[str, Any]] = None,
) -> AuditLog:
    """
    Convenience wrapper for system/background actions (no user, no request).
    """
    return await write(
        db,
        entity_type=entity_type,
        action=action,
        tenant_id=tenant_id,
        user_id=None,
        entity_id=entity_id,
        diff=diff,
    )


# ── Read helpers (used by the audit API endpoints) ─────────────────────────────

from sqlalchemy import select, func, desc
from app.modules.tenants.models import Tenant
from app.modules.users.models import User


async def list_logs(
    db: AsyncSession,
    *,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    Fetch audit logs with optional filters.
    Returns dicts with tenant_public_id and user_public_id resolved via JOIN.
    Pass tenant_id=None to get platform-level logs (super admin use).
    """
    q = (
        select(
            AuditLog,
            Tenant.public_id.label("tenant_public_id"),
            User.public_id.label("user_public_id"),
        )
        .outerjoin(Tenant, AuditLog.tenant_id == Tenant.id)
        .outerjoin(User, AuditLog.user_id == User.id)
    )
    if tenant_id is not None:
        q = q.where(AuditLog.tenant_id == tenant_id)
    if user_id is not None:
        q = q.where(AuditLog.user_id == user_id)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if action:
        q = q.where(AuditLog.action == action)
    q = q.order_by(desc(AuditLog.created_at)).limit(limit).offset(offset)
    result = await db.execute(q)
    rows = result.all()
    return [
        {
            "id": row.AuditLog.id,
            "tenant_public_id": row.tenant_public_id,
            "user_public_id": row.user_public_id,
            "entity_type": row.AuditLog.entity_type,
            "entity_id": row.AuditLog.entity_id,
            "action": row.AuditLog.action,
            "diff": row.AuditLog.diff,
            "ip_address": row.AuditLog.ip_address,
            "user_agent": row.AuditLog.user_agent,
            "created_at": row.AuditLog.created_at,
        }
        for row in rows
    ]


async def count_logs(
    db: AsyncSession,
    *,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    action: Optional[str] = None,
) -> int:
    q = select(func.count(AuditLog.id))
    if tenant_id is not None:
        q = q.where(AuditLog.tenant_id == tenant_id)
    if user_id is not None:
        q = q.where(AuditLog.user_id == user_id)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if action:
        q = q.where(AuditLog.action == action)
    result = await db.execute(q)
    return result.scalar_one()
