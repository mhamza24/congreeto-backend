from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List

logger = logging.getLogger(__name__)

from sqlalchemy import select, func, not_, exists
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.tenants.models import Tenant, TenantInvite
from app.modules.models.tenant_user import TenantUser
from app.core.enums import TenantStatus, TenantRole, TenantUserStatus, ChatbotStatus, DocStatus, CrawlStatus


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
        select(TenantUser)
        .options(selectinload(TenantUser.user))
        .where(TenantUser.public_id == public_id)
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
        .join(User, (User.id == TenantUser.user_id) & (User.deleted_at.is_(None)))
        .where(TenantUser.tenant_id == tenant_id)
    )
    if role:
        query = query.where(TenantUser.role == role)

    # Count only rows that have a live user attached (same join condition)
    total_result = await db.execute(
        select(func.count()).select_from(
            select(TenantUser)
            .join(User, (User.id == TenantUser.user_id) & (User.deleted_at.is_(None)))
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
    Seat count for Gate 3 seat limit enforcement.
    ACTIVE and INVITED members both consume a seat.
    suspended / deactivated do NOT consume seats.
    """
    result = await db.execute(
        select(func.count(TenantUser.id)).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.status.in_([TenantUserStatus.ACTIVE, TenantUserStatus.INVITED]),
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


# =============================================================================
# TENANT INVITE
# =============================================================================

async def get_invites_last_24h(
    db: AsyncSession,
    *,
    tenant_id: int,
    invitee_user_id: int,
) -> List[TenantInvite]:
    """
    Returns all invites sent to this (tenant, invitee) pair in the last 24 hours,
    ordered most-recent first. Used to enforce the rate-limit / lock logic.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    result = await db.execute(
        select(TenantInvite)
        .where(
            TenantInvite.tenant_id == tenant_id,
            TenantInvite.invitee_user_id == invitee_user_id,
            TenantInvite.sent_at > cutoff,
        )
        .order_by(TenantInvite.sent_at.desc())
    )
    return list(result.scalars().all())


async def create_invite(
    db: AsyncSession,
    *,
    tenant_id: int,
    invitee_user_id: int,
    invited_by_user_id: Optional[int],
    role: TenantRole,
    otp_id: int,
    expires_at: datetime,
) -> TenantInvite:
    now = datetime.now(timezone.utc)
    invite = TenantInvite(
        tenant_id=tenant_id,
        invitee_user_id=invitee_user_id,
        invited_by_user_id=invited_by_user_id,
        role=role,
        otp_id=otp_id,
        sent_at=now,
        expires_at=expires_at,
    )
    db.add(invite)
    await db.flush()
    await db.refresh(invite)
    return invite


async def get_invite_by_otp_id(
    db: AsyncSession, *, otp_id: int
) -> Optional[TenantInvite]:
    result = await db.execute(
        select(TenantInvite).where(TenantInvite.otp_id == otp_id)
    )
    return result.scalar_one_or_none()


async def consume_invite(db: AsyncSession, *, invite: TenantInvite) -> None:
    invite.consumed_at = datetime.now(timezone.utc)
    await db.flush()


# =============================================================================
# ADMIN — CROSS-TENANT COUNTS (super-admin only)
# =============================================================================

async def count_members_by_status(
    db: AsyncSession, *, tenant_id: int
) -> dict:
    """Returns counts of TenantUser rows broken down by status."""
    result = await db.execute(
        select(TenantUser.status, func.count(TenantUser.id))
        .where(TenantUser.tenant_id == tenant_id)
        .group_by(TenantUser.status)
    )
    rows = result.all()
    counts = {r[0]: r[1] for r in rows}
    total = sum(counts.values())
    return {
        "total":     total,
        "active":    counts.get(TenantUserStatus.ACTIVE, 0),
        "invited":   counts.get(TenantUserStatus.INVITED, 0),
        "suspended": counts.get(TenantUserStatus.SUSPENDED, 0),
    }


async def count_chatbots_by_status(
    db: AsyncSession, *, tenant_id: int
) -> dict:
    """Returns counts of ChatbotConfig rows broken down by status."""
    from app.modules.chatbot.models import ChatbotConfig  # avoid circular import
    result = await db.execute(
        select(ChatbotConfig.status, func.count(ChatbotConfig.id))
        .where(ChatbotConfig.tenant_id == tenant_id)
        .group_by(ChatbotConfig.status)
    )
    rows = result.all()
    counts = {r[0]: r[1] for r in rows}
    total = sum(counts.values())
    return {
        "total":    total,
        "active":   counts.get(ChatbotStatus.ACTIVE, 0),
        "draft":    counts.get(ChatbotStatus.DRAFT, 0),
        "inactive": counts.get(ChatbotStatus.INACTIVE, 0),
    }


async def count_documents_by_status(
    db: AsyncSession, *, tenant_id: int
) -> dict:
    """Returns counts of Document rows broken down by status."""
    from app.modules.chatbot.models import Document  # avoid circular import
    result = await db.execute(
        select(Document.status, func.count(Document.id))
        .where(Document.tenant_id == tenant_id)
        .group_by(Document.status)
    )
    rows = result.all()
    counts = {r[0]: r[1] for r in rows}
    total = sum(counts.values())
    return {
        "total":      total,
        "ready":      counts.get(DocStatus.READY, 0),
        "processing": counts.get(DocStatus.PROCESSING, 0),
        "uploading":  counts.get(DocStatus.UPLOADING, 0),
        "failed":     counts.get(DocStatus.FAILED, 0),
    }


async def count_pending_crawl_jobs(
    db: AsyncSession, *, tenant_id: int
) -> dict:
    """Returns counts of in-flight CrawlJob and Document rows for the tenant."""
    from app.modules.chatbot.models import CrawlJob, Document  # avoid circular import
    crawl_result = await db.execute(
        select(CrawlJob.status, func.count(CrawlJob.id))
        .where(
            CrawlJob.tenant_id == tenant_id,
            CrawlJob.status.in_([CrawlStatus.QUEUED, CrawlStatus.RUNNING]),
        )
        .group_by(CrawlJob.status)
    )
    crawl_counts = {r[0]: r[1] for r in crawl_result.all()}

    doc_result = await db.execute(
        select(Document.status, func.count(Document.id))
        .where(
            Document.tenant_id == tenant_id,
            Document.status.in_([DocStatus.UPLOADING, DocStatus.PROCESSING]),
        )
        .group_by(Document.status)
    )
    doc_counts = {r[0]: r[1] for r in doc_result.all()}

    return {
        "crawl_jobs_queued":    crawl_counts.get(CrawlStatus.QUEUED, 0),
        "crawl_jobs_running":   crawl_counts.get(CrawlStatus.RUNNING, 0),
        "documents_processing": doc_counts.get(DocStatus.PROCESSING, 0),
        "documents_uploading":  doc_counts.get(DocStatus.UPLOADING, 0),
    }


async def get_pending_invites_without_membership(
    db: AsyncSession,
    *,
    tenant_id: int,
) -> List[TenantInvite]:
    """
    Returns unconsumed, non-expired invites for this tenant where the invitee
    has no TenantUser row yet. Used to show legacy pending invites in the
    member list before the invitee accepts.
    """
    from app.modules.users.models import User  # avoid circular import
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(TenantInvite)
        .options(selectinload(TenantInvite.invitee))
        .where(
            TenantInvite.tenant_id == tenant_id,
            TenantInvite.consumed_at.is_(None),
            TenantInvite.expires_at > now,
            not_(
                exists(
                    select(TenantUser.id).where(
                        TenantUser.tenant_id == tenant_id,
                        TenantUser.user_id == TenantInvite.invitee_user_id,
                    )
                )
            ),
        )
        .order_by(TenantInvite.sent_at.asc())
    )
    return list(result.scalars().all())