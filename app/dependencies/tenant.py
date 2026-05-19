# app/dependencies/tenant.py
"""
Reusable FastAPI dependency for all tenant-scoped endpoints.

Usage:
    from app.dependencies.tenant import TenantContext, get_tenant_context

    @router.post("/...")
    async def my_endpoint(
        ctx: TenantContext = Depends(get_tenant_context),
        db: DBDep,
    ):
        if ctx.is_read_only:
            raise HTTPException(402, "Account is past due. Please update billing.")
        ...

Gate order enforced here so individual endpoints don't repeat the logic:
    1. Tenant exists
    2. Gate 1  — tenant.status: pending_plan → 402, suspended/cancelled → 403
    3. Membership — caller is a member of this tenant
    4. Member status — member must be active (not suspended/deactivated/invited)
    5. Gate 2  — subscription.status:
                    past_due           → is_read_only=True (caller must check before writes)
                    cancelled / paused → 403
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.database import get_db
from app.core.enums import TenantStatus
from app.core.redis import redis_client
from app.dependencies.auth import get_current_user
from app.modules.billing import repository as billing_repo
from app.modules.billing.models import TenantSubscription
from app.modules.models.tenant_user import TenantUser
from app.modules.tenants import repository as tenant_repo
from app.modules.tenants.models import Tenant
from app.modules.users.models import User

settings = get_settings()
logger = logging.getLogger(__name__)

_CTX_CACHE_TTL = settings.TENANT_CONTEXT_CACHE_TTL


def _ctx_cache_key(tenant_public_id: str, user_id: int) -> str:
    return f"tc:{tenant_public_id}:{user_id}"


@dataclass
class TenantContext:
    """
    Injected into every tenant-scoped endpoint via Depends(get_tenant_context).

    Fields:
        tenant       — the Tenant ORM row (Gate 1 already passed)
        membership   — the TenantUser row for the calling user
        subscription — the active TenantSubscription (None if no plan yet)
        is_read_only — True when subscription is past_due; write endpoints
                       must raise HTTP 402 before mutating state
    """
    tenant:       Tenant
    membership:   TenantUser
    subscription: Optional[TenantSubscription]
    is_read_only: bool


async def _build_context_from_db(
    db: AsyncSession,
    tenant_public_id: str,
    current_user: User,
) -> TenantContext:
    """Full DB path: validates status, returns TenantContext and the IDs to cache."""
    tenant = await tenant_repo.get_tenant_by_public_id(db, public_id=tenant_public_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    # Safety net only — new tenants always start ACTIVE (billing gate enforced in create_tenant).
    # This fires only if a tenant is manually set to PENDING_PLAN via admin tooling.
    if tenant.status == TenantStatus.PENDING_PLAN:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="This workspace has no active plan. Please contact support.",
        )
    if tenant.status in (TenantStatus.SUSPENDED, TenantStatus.CANCELLED):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This tenant account is suspended or cancelled. Please contact support.",
        )

    tu = await tenant_repo.get_tenant_user(db, tenant_id=tenant.id, user_id=current_user.id)
    if not tu:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this tenant.")

    if not tu.is_accessible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your access to this tenant has been suspended or deactivated.",
        )

    sub = await billing_repo.get_active_subscription(db, tenant_id=tenant.id)
    is_read_only = False

    if sub:
        if sub.is_blocked:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your subscription has been cancelled or paused. Please contact support.",
            )
        if sub.is_past_due:
            is_read_only = True

    return TenantContext(tenant=tenant, membership=tu, subscription=sub, is_read_only=is_read_only)


async def get_tenant_context(
    tenant_public_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenantContext:
    # ── Step 0: email must be verified ───────────────────────────────────────
    if current_user.email_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email address not verified. Please verify your email before accessing tenant resources.",
        )

    cache_key = _ctx_cache_key(tenant_public_id, current_user.id)

    # ── Fast path: cache hit ──────────────────────────────────────────────────
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            data = json.loads(cached)
            tenant = await db.get(Tenant, data["tenant_id"])
            tu = await db.get(TenantUser, data["tu_id"])
            sub = await db.get(TenantSubscription, data["sub_id"]) if data.get("sub_id") else None
            if tenant and tu:
                return TenantContext(
                    tenant=tenant,
                    membership=tu,
                    subscription=sub,
                    is_read_only=data["is_read_only"],
                )
    except Exception:
        logger.debug("TenantContext cache read failed — falling back to DB", exc_info=True)

    # ── Slow path: full DB validation ─────────────────────────────────────────
    ctx = await _build_context_from_db(db, tenant_public_id, current_user)

    # ── Write cache (fire-and-forget; never block the response on cache errors) ─
    try:
        payload = json.dumps({
            "tenant_id":   ctx.tenant.id,
            "tu_id":       ctx.membership.id,
            "sub_id":      ctx.subscription.id if ctx.subscription else None,
            "is_read_only": ctx.is_read_only,
        })
        await redis_client.setex(cache_key, _CTX_CACHE_TTL, payload)
    except Exception:
        logger.debug("TenantContext cache write failed — continuing without cache", exc_info=True)

    return ctx


def require_write(ctx: TenantContext) -> None:
    """
    Call at the top of any write/mutating endpoint when using TenantContext.
    Checks both role and billing status before allowing mutations.
    """
    if not ctx.membership.can_write:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )
    if ctx.is_read_only:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "Your account has an outstanding payment. "
                "Read access is still available. "
                "Please update your billing details to resume write operations."
            ),
        )
