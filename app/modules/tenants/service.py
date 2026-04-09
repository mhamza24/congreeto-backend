from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SlugExistError
from app.core.redis import redis_client
from app.modules.auth import repository as auth_repo
from app.modules.tenants import repository as repo
from app.modules.tenants import schemas
from app.modules.tenants import tasks as background_tasks
from app.modules.users import repository as user_repo
from app.modules.tenants.models import Tenant
from app.modules.models.tenant_user import TenantUser
from app.modules.users.models import User
from app.core.enums import TenantStatus, TenantRole, TenantUserStatus, UserStatus, OTPPurpose
from app.utils.hashing_utils import hash_password, hash_identity, hash_otp
from app.config.settings import get_settings
from app.modules.billing import repository as billing_repo
import logging

logger = logging.getLogger(__name__)

settings = get_settings()

INVITE_TTL_HOURS = 72


# =============================================================================
# SEAT LIMIT HELPER
# =============================================================================


async def _get_seat_info(db: AsyncSession, tenant_id: int) -> dict:
    """
    Returns seat usage info driven by the active plan + addon grants.
    Falls back to DEFAULT_SEAT_LIMIT when the tenant has no active subscription
    (e.g. still in pending_plan state).
    """
    seats_used = await repo.count_active_members(db, tenant_id=tenant_id)

    sub = await billing_repo.get_active_subscription(db, tenant_id=tenant_id)
    if sub:
        addon_seats = await billing_repo.get_addon_grant_total(
            db, tenant_id=tenant_id, metric="max_users"
        )
        seats_total = sub.plan.get_limit("max_users", settings.DEFAULT_SEAT_LIMIT) + addon_seats
    else:
        seats_total = settings.DEFAULT_SEAT_LIMIT

    return {
        "seats_used": seats_used,
        "seats_total": seats_total,
        "seats_remaining": max(0, seats_total - seats_used),
    }


# =============================================================================
# TENANT OPERATIONS
# =============================================================================


async def create_tenant(
    db: AsyncSession,
    *,
    payload: schemas.TenantCreateRequest,
    owner: User,
) -> schemas.TenantResponse:
    """
    Creates a new tenant and assigns the calling user as primary owner.
    Owner immediately consumes 1 of the DEFAULT_SEAT_LIMIT seats.
    Status starts as pending_plan — frontend redirects to billing.
    """
    if await repo.slug_exists(db, slug=payload.slug):
        raise SlugExistError()

    tenant = Tenant.from_schema(payload, status=TenantStatus.PENDING_PLAN)
    tenant = await repo.create_tenant(db, tenant=tenant)

    db.add(
        TenantUser(
            tenant_id=tenant.id,
            user_id=owner.id,
            role=TenantRole.OWNER,
            is_primary_owner=True,
            status=TenantUserStatus.ACTIVE,
            joined_at=datetime.now(timezone.utc),
        )
    )

    await db.commit()
    await db.refresh(tenant)
    return schemas.TenantResponse.model_validate(tenant)


async def get_my_tenant(
    db: AsyncSession,
    *,
    current_user: int,
    tenant_public_id: str,
    preloaded_tenant: Optional["Tenant"] = None,
    preloaded_tu: Optional["TenantUser"] = None,
    preloaded_sub=None,
) -> schemas.MyTenantContext:
    tenant = preloaded_tenant or await _get_tenant_or_404(db, public_id=tenant_public_id)
    tu     = preloaded_tu    or await _get_membership_or_403(db, tenant_id=tenant.id, user_id=current_user)

    if not tu.is_accessible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your access to this tenant has been suspended or deactivated.",
        )

    seat_info = await _get_seat_info(db, tenant_id=tenant.id)

    sub = preloaded_sub if preloaded_sub is not None else await billing_repo.get_active_subscription(db, tenant_id=tenant.id)
    is_read_only = bool(sub and sub.is_past_due)

    return schemas.MyTenantContext(
        tenant=schemas.TenantSummary.model_validate(tenant),
        role=tu.role,
        status=tu.status,
        is_owner=tu.is_primary_owner,
        joined_at=tu.joined_at,
        seats_used=seat_info["seats_used"],
        seats_total=seat_info["seats_total"],
        seats_remaining=seat_info["seats_remaining"],
        is_read_only=is_read_only,
    )


async def get_my_tenants(
    db: AsyncSession,
    *,
    current_user: User,
) -> schemas.UserTenantsResponse:
    memberships = await repo.get_user_tenants(db, user_id=current_user.id)
    items = [
        schemas.UserTenantItem(
            tenant=schemas.TenantSummary.model_validate(tu.tenant),
            role=tu.role,
            status=tu.status,
            is_primary_owner=tu.is_primary_owner,
            joined_at=tu.joined_at,
        )
        for tu in memberships
    ]
    return schemas.UserTenantsResponse(total=len(items), tenants=items)


async def update_tenant(
    db: AsyncSession,
    *,
    payload: schemas.TenantUpdateRequest,
    tenant: Tenant,
    caller_tu: TenantUser,
) -> schemas.TenantResponse:
    if not caller_tu.is_owner_or_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins and owners can update tenant details.",
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tenant, field, value)

    await db.commit()
    await db.refresh(tenant)
    return schemas.TenantResponse.model_validate(tenant)


async def update_tenant_status(
    db: AsyncSession,
    *,
    payload: schemas.TenantStatusUpdateRequest,
    tenant_public_id: str,
) -> schemas.TenantResponse:
    """Super-admin only."""
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    tenant.status = payload.status
    await db.commit()
    await db.refresh(tenant)
    return schemas.TenantResponse.model_validate(tenant)


# =============================================================================
# MEMBER OPERATIONS
# =============================================================================


async def list_members(
    db: AsyncSession,
    *,
    tenant: Tenant,
    role: Optional[TenantRole] = None,
    skip: int = 0,
    limit: int = 50,
) -> schemas.MemberListResponse:
    members, total = await repo.list_tenant_members(
        db, tenant_id=tenant.id, role=role, skip=skip, limit=limit
    )
    seat_info = await _get_seat_info(db, tenant_id=tenant.id)

    return schemas.MemberListResponse(
        total=total,
        **seat_info,
        members=[_build_member_response(m) for m in members],
    )


async def invite_user(
    db: AsyncSession,
    *,
    payload: schemas.InviteUserRequest,
    tenant: Tenant,
    caller_tu: TenantUser,
) -> schemas.InviteResponse:
    """
    Admin/owner invites a new user.
    Gate 3: seat limit enforced from active plan + addon grants.
    Purchase extra_users addon to raise the limit.
    """
    tu = caller_tu
    if not tu.is_owner_or_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins and owners can invite users.",
        )

    # Gate 3 — seat limit check
    seat_info = await _get_seat_info(db, tenant_id=tenant.id)
    if seat_info["seats_remaining"] <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Seat limit reached. Your plan includes {seat_info['seats_total']} users "
                f"({seat_info['seats_used']} currently active). "
                "Purchase additional user seats to invite more members."
            ),
        )

    # Already a member?
    existing_user = await user_repo.get_user_by_email(db, email=payload.email)
    if existing_user:
        if await repo.is_member(db, tenant_id=tenant.id, user_id=existing_user.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This user is already a member of your team.",
            )

    expires_at = datetime.now(timezone.utc) + timedelta(hours=INVITE_TTL_HOURS)

    # Pre-create user with status=INVITED if they don't have an account yet
    invitee = existing_user
    if not invitee:
        invitee = User(
            email      = payload.email.lower(),
            email_hash = hash_identity(payload.email),
            status     = UserStatus.INVITED,
        )
        invitee = await user_repo.create_user(db, user=invitee)

    # Create OTP record in DB (same table used by email verification)
    # expires_in_minutes = 72h * 60 = 4320 min
    raw_otp = await auth_repo.create_otp(
        db,
        user_id            = invitee.id,
        purpose            = OTPPurpose.TENANT_INVITE,
        expires_in_minutes = INVITE_TTL_HOURS * 60,
    )

    # Store invite metadata in Redis keyed by otp_hash for fast accept lookup
    otp_hash = hash_otp(raw_otp)
    await redis_client.set(
        f"invite_otp:{otp_hash}",
        json.dumps({
            "user_id":          invitee.id,
            "tenant_public_id": tenant.public_id,
            "role":             payload.role.value,
            "invited_by_id":    caller_tu.user_id,
        }),
        ex=INVITE_TTL_HOURS * 3600,
    )

    invite_link = f"{settings.FRONTEND_URL}/invite/accept?otp={raw_otp}"
    celery_task = background_tasks.send_invite_email_task.delay(
        to           = payload.email,
        first_name   = invitee.first_name or payload.email.split("@")[0],
        inviter_name = caller_tu.user.full_name if hasattr(caller_tu, "user") and caller_tu.user else "Team",
        tenant_name  = tenant.name,
        invite_link  = invite_link,
        role         = payload.role.value,
    )
    logger.info(f"Invite email enqueued: task={celery_task.id} recipient={payload.email}")

    return schemas.InviteResponse(
        email=payload.email,
        role=payload.role,
        expires_at=expires_at,
        **seat_info,
    )


async def accept_invite(
    db: AsyncSession,
    *,
    payload: schemas.AcceptInviteRequest,
) -> schemas.AcceptInviteResponse:
    # 1. Fast Redis lookup — get invite metadata by hashed OTP
    otp_hash = hash_otp(payload.code)
    raw_data = await redis_client.get(f"invite_otp:{otp_hash}")
    if not raw_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invite link.",
        )

    invite_data  = json.loads(raw_data)
    user_id      = invite_data["user_id"]
    role         = TenantRole(invite_data["role"])
    invited_by_id = invite_data.get("invited_by_id")

    # 2. Verify OTP against DB record — handles attempts + consumed_at
    otp_record = await auth_repo.get_active_otp(
        db, user_id=user_id, purpose=OTPPurpose.TENANT_INVITE
    )
    if otp_record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invite link.",
        )

    is_valid = await auth_repo.verify_otp(db, record=otp_record, raw_code=payload.code)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invite link.",
        )

    # 3. Consume Redis key — single use
    await redis_client.delete(f"invite_otp:{otp_hash}")

    # 4. Load tenant, verify it's still active, and re-check seat limit at acceptance time
    tenant = await _get_tenant_or_404(db, public_id=invite_data["tenant_public_id"])
    if tenant.status in (TenantStatus.SUSPENDED, TenantStatus.CANCELLED):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This tenant account is no longer active.",
        )
    seat_info = await _get_seat_info(db, tenant_id=tenant.id)
    if seat_info["seats_remaining"] <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "This tenant has reached its user seat limit. "
                "Please ask the owner to purchase additional seats."
            ),
        )

    # 5. Load the pre-created invited user
    user = await user_repo.get_user_by_id(db, id=user_id)

    if await repo.is_member(db, tenant_id=tenant.id, user_id=user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already a member of this team.",
        )

    # 6. If user is still in INVITED state, activate them with submitted profile
    if user.status == UserStatus.INVITED:
        user.first_name        = payload.first_name
        user.last_name         = payload.last_name
        user.password_hash     = hash_password(payload.password)
        user.status            = UserStatus.ACTIVE
        user.email_verified_at = datetime.now(timezone.utc)
        await db.flush()

    # 7. Add to tenant
    db.add(
        TenantUser(
            tenant_id  = tenant.id,
            user_id    = user.id,
            role       = role,
            invited_by = invited_by_id,
            status     = TenantUserStatus.ACTIVE,
            joined_at  = datetime.now(timezone.utc),
        )
    )

    await db.commit()
    return schemas.AcceptInviteResponse(public_id=str(user.public_id))


async def update_member_role(
    db: AsyncSession,
    *,
    payload: schemas.UpdateMemberRoleRequest,
    caller_tu: TenantUser,
    tenant: Tenant,
    member_public_id: str,
) -> schemas.TenantMemberResponse:
    if not caller_tu.is_owner_or_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins and owners can change member roles.",
        )

    target_tu = await repo.get_tenant_user_by_public_id(db, public_id=member_public_id)
    if not target_tu or target_tu.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")

    if target_tu.is_primary_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot change the primary owner's role.",
        )

    target_tu.role = payload.role
    await db.commit()
    await db.refresh(target_tu)
    return _build_member_response(target_tu)


async def update_member_status(
    db: AsyncSession,
    *,
    payload: schemas.UpdateMemberStatusRequest,
    caller_tu: TenantUser,
    current_user_id: int,
    tenant: Tenant,
    member_public_id: str,
) -> schemas.TenantMemberResponse:
    """
    Admin/owner suspends or reactivates a member within this tenant only.
    Suspended/deactivated members free up their seat immediately.
    Reactivating checks seat limit again before allowing.
    """
    if not caller_tu.is_owner_or_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins and owners can change member status.",
        )

    target_tu = await repo.get_tenant_user_by_public_id(db, public_id=member_public_id)
    if not target_tu or target_tu.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found."
        )

    if target_tu.is_primary_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot change the primary owner's status.",
        )

    if target_tu.user_id == current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot change your own status.",
        )

    # If reactivating — check seat limit first
    if payload.status == TenantUserStatus.ACTIVE:
        seat_info = await _get_seat_info(db, tenant_id=tenant.id)
        if seat_info["seats_remaining"] <= 0:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"Cannot reactivate member. Seat limit reached "
                    f"({seat_info['seats_used']}/{seat_info['seats_total']} seats used). "
                    "Purchase additional seats to reactivate this member."
                ),
            )

    target_tu.status = payload.status
    await db.commit()
    await db.refresh(target_tu)
    return _build_member_response(target_tu)


async def remove_member(
    db: AsyncSession,
    *,
    caller_tu: TenantUser,
    current_user_id: int,
    tenant: Tenant,
    member_public_id: str,
) -> schemas.RemoveMemberResponse:
    target_tu = await repo.get_tenant_user_by_public_id(db, public_id=member_public_id)
    if not target_tu or target_tu.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")

    is_self = target_tu.user_id == current_user_id
    if not is_self and not caller_tu.is_owner_or_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to remove this member.",
        )

    if target_tu.is_primary_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The primary owner cannot be removed from the tenant.",
        )

    await db.delete(target_tu)
    await db.commit()
    return schemas.RemoveMemberResponse()


# =============================================================================
# PRIVATE HELPERS
# =============================================================================

async def _get_tenant_or_404(db: AsyncSession, *, public_id: str) -> Tenant:
    tenant = await repo.get_tenant_by_public_id(db, public_id=public_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )
    return tenant


async def _get_membership_or_403(
    db: AsyncSession, *, tenant_id: int, user_id: int
) -> TenantUser:
    tu = await repo.get_tenant_user(db, tenant_id=tenant_id, user_id=user_id)
    if not tu:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this tenant.",
        )
    return tu


def _build_member_response(tu: TenantUser) -> schemas.TenantMemberResponse:
    user = tu.user
    return schemas.TenantMemberResponse(
        public_id=tu.public_id,
        role=tu.role,
        status=tu.status,
        is_primary_owner=tu.is_primary_owner,
        joined_at=tu.joined_at,
        created_at=tu.created_at,
        user_public_id=user.public_id,
        user_last_login=user.last_login_at,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        avatar_url=user.avatar_url,
    )