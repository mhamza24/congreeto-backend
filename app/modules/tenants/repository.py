from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.tenants.models import Tenant
from app.modules.models.tenant_user import TenantUser
from app.core.enums import TenantStatus, TenantRole, TenantUserStatus


# =============================================================================
# TENANT READS
# =============================================================================

async def get_tenant_by_id(
    db: AsyncSession, *, id: int
) -> Optional[Tenant]:
    result = await db.execute(
        select(Tenant).where(Tenant.id == id, Tenant.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_tenant_by_public_id(
    db: AsyncSession, *, public_id: str
) -> Optional[Tenant]:
    result = await db.execute(
        select(Tenant).where(Tenant.public_id == public_id, Tenant.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_tenant_by_slug(
    db: AsyncSession, *, slug: str
) -> Optional[Tenant]:
    result = await db.execute(
        select(Tenant).where(Tenant.slug == slug, Tenant.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def list_tenants(
    db: AsyncSession,
    *,
    status: Optional[TenantStatus] = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[List[Tenant], int]:
    query = select(Tenant).where(Tenant.deleted_at.is_(None))
    if status:
        query = query.where(Tenant.status == status)
    total_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = total_result.scalar_one()
    result = await db.execute(
        query.order_by(Tenant.created_at.desc()).offset(skip).limit(limit)
    )
    return result.scalars().all(), total


async def slug_exists(
    db: AsyncSession, *, slug: str, exclude_id: Optional[int] = None
) -> bool:
    query = select(Tenant.id).where(
        Tenant.slug == slug, Tenant.deleted_at.is_(None)
    )
    if exclude_id:
        query = query.where(Tenant.id != exclude_id)
    result = await db.execute(query)
    return result.scalar_one_or_none() is not None


# =============================================================================
# TENANT WRITES
# =============================================================================

async def create_tenant(db: AsyncSession, *, tenant: Tenant) -> Tenant:
    db.add(tenant)
    await db.flush()
    await db.refresh(tenant)
    return tenant


async def soft_delete_tenant(db: AsyncSession, *, tenant: Tenant) -> None:
    tenant.deleted_at = datetime.now(timezone.utc)
    await db.flush()


# =============================================================================
# TENANT USER READS
# =============================================================================

async def get_tenant_user(
    db: AsyncSession, *, tenant_id: int, user_id: int
) -> Optional[TenantUser]:
    result = await db.execute(
        select(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_tenant_user_by_public_id(
    db: AsyncSession, *, public_id: str
) -> Optional[TenantUser]:
    result = await db.execute(
        select(TenantUser).where(TenantUser.public_id == public_id)
    )
    return result.scalar_one_or_none()


async def list_tenant_members(
    db: AsyncSession,
    *,
    tenant_id: int,
    role: Optional[TenantRole] = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[List[TenantUser], int]:
    from app.modules.users.models import User  # avoid circular import

    query = (
        select(TenantUser)
        .options(selectinload(TenantUser.user))
        .join(User, User.id == TenantUser.user_id)
        .where(TenantUser.tenant_id == tenant_id)
    )
    if role:
        query = query.where(TenantUser.role == role)

    total_result = await db.execute(
        select(func.count()).select_from(
            select(TenantUser)
            .where(TenantUser.tenant_id == tenant_id)
            .subquery()
        )
    )
    total = total_result.scalar_one()

    result = await db.execute(
        query.order_by(TenantUser.created_at.asc()).offset(skip).limit(limit)
    )
    return result.scalars().all(), total


async def get_user_tenants(
    db: AsyncSession, *, user_id: int
) -> List[TenantUser]:
    result = await db.execute(
        select(TenantUser)
        .options(selectinload(TenantUser.tenant))
        .where(TenantUser.user_id == user_id)
        .order_by(TenantUser.created_at.asc())
    )
    return result.scalars().all()


async def count_active_members(
    db: AsyncSession, *, tenant_id: int
) -> int:
    """
    Active seat count for Gate 3 seat limit enforcement.
    Only ACTIVE members consume a seat.
    invited / suspended / deactivated do NOT consume seats.
    """
    result = await db.execute(
        select(func.count(TenantUser.id)).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.status == TenantUserStatus.ACTIVE,
        )
    )
    return result.scalar_one()


async def is_member(
    db: AsyncSession, *, tenant_id: int, user_id: int
) -> bool:
    result = await db.execute(
        select(TenantUser.id).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.user_id == user_id,
        )
    )
    return result.scalar_one_or_none() is not None