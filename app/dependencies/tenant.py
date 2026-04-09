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

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enums import TenantStatus
from app.dependencies.auth import get_current_user
from app.modules.billing import repository as billing_repo
from app.modules.billing.models import TenantSubscription
from app.modules.models.tenant_user import TenantUser
from app.modules.tenants import repository as tenant_repo
from app.modules.tenants.models import Tenant
from app.modules.users.models import User


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


async def get_tenant_context(
    tenant_public_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenantContext:
    # ── Step 1: tenant exists ─────────────────────────────────────────────────
    tenant = await tenant_repo.get_tenant_by_public_id(db, public_id=tenant_public_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )

    # ── Step 2: Gate 1 — tenant status ───────────────────────────────────────
    if tenant.status == TenantStatus.PENDING_PLAN:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="This tenant has not selected a plan yet. Please complete billing setup.",
        )
    if tenant.status in (TenantStatus.SUSPENDED, TenantStatus.CANCELLED):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This tenant account is suspended or cancelled. Please contact support.",
        )

    # ── Step 3: membership ────────────────────────────────────────────────────
    tu = await tenant_repo.get_tenant_user(db, tenant_id=tenant.id, user_id=current_user.id)
    if not tu:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this tenant.",
        )

    # ── Step 4: member status ─────────────────────────────────────────────────
    if not tu.is_accessible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your access to this tenant has been suspended or deactivated.",
        )

    # ── Step 5: Gate 2 — subscription status ─────────────────────────────────
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

    return TenantContext(
        tenant=tenant,
        membership=tu,
        subscription=sub,
        is_read_only=is_read_only,
    )


def require_write(ctx: TenantContext) -> None:
    """
    Call at the top of any write/mutating service operation when using TenantContext.

    Usage:
        require_write(ctx)   # raises 402 if past_due, no-op otherwise

    This is a plain function (not a Depends) so it can be called inside service
    functions that already received the context from the API layer.
    """
    if ctx.is_read_only:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "Your account has an outstanding payment. "
                "Read access is still available. "
                "Please update your billing details to resume write operations."
            ),
        )
