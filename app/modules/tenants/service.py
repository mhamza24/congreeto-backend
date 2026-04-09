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
import logging

logger = logging.getLogger(__name__)

settings = get_settings()

INVITE_TTL_HOURS = 72


# =============================================================================
# SEAT LIMIT HELPER
# =============================================================================


async def _get_seat_info(db: AsyncSession, tenant_id: int) -> dict:
    """
    Returns seat usage info.
    DEFAULT_SEAT_LIMIT from settings = 3 (owner + 2 members).
    When billing is live: replace with plan.limits['max_users'] + addon_qty.
    """
    seats_used = await repo.count_active_members(db, tenant_id=tenant_id)
    seats_total = settings.DEFAULT_SEAT_LIMIT
    # TODO: when billing is live replace above with:
    # plan        = await repo.get_tenant_active_plan(db, tenant_id=tenant_id)
    # addon_seats = await repo.get_addon_seat_count(db, tenant_id=tenant_id)
    # seats_total = plan.limits['max_users'] + addon_seats

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

    await db.refresh(tenant)
    return schemas.TenantResponse.model_validate(tenant)


async def get_my_tenant(
    db: AsyncSession,
    *,
    current_user: User,
    tenant_public_id: str,
) -> schemas.MyTenantContext:
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    tu = await _get_membership_or_403(db, tenant_id=tenant.id, user_id=current_user.id)

    if not tu.is_accessible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your access to this tenant has been suspended or deactivated.",
        )

    seat_info = await _get_seat_info(db, tenant_id=tenant.id)

    return schemas.MyTenantContext(
        tenant=schemas.TenantSummary.model_validate(tenant),
        role=tu.role,
        status=tu.status,  # ← was missing
        is_owner=tu.is_primary_owner,
        joined_at=tu.joined_at,
        seats_used=seat_info["seats_used"],  # ← was missing
        seats_total=seat_info["seats_total"],  # ← was missing
        seats_remaining=seat_info["seats_remaining"],  # ← was missing
    )


async def update_tenant(
    db: AsyncSession,
    *,
    payload: schemas.TenantUpdateRequest,
    current_user: User,
    tenant_public_id: str,
) -> schemas.TenantResponse:
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    tu = await _get_membership_or_403(db, tenant_id=tenant.id, user_id=current_user.id)

    if not tu.is_owner_or_admin:
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
    current_user: User,
    tenant_public_id: str,
    role: Optional[TenantRole] = None,
    skip: int = 0,
    limit: int = 50,
) -> schemas.MemberListResponse:
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    await _get_membership_or_403(db, tenant_id=tenant.id, user_id=current_user.id)

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
    current_user: User,
    tenant_public_id: str,
) -> schemas.InviteResponse:
    """
    Admin/owner invites a new user.
    Gate 3: max DEFAULT_SEAT_LIMIT active members.
    Owner already consumes seat 1, so by default only 2 more can be invited.
    To add more: purchase extra_users addon (billing — coming soon).
    """
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    tu = await _get_membership_or_403(db, tenant_id=tenant.id, user_id=current_user.id)

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
            "invited_by_id":    current_user.id,
        }),
        ex=INVITE_TTL_HOURS * 3600,
    )

    invite_link = f"{settings.FRONTEND_URL}/invite/accept?otp={raw_otp}"
    celery_task = background_tasks.send_invite_email_task.delay(
        to           = payload.email,
        first_name   = invitee.first_name or payload.email.split("@")[0],
        inviter_name = current_user.full_name,
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

    # 4. Load tenant and re-check seat limit at acceptance time
    tenant = await _get_tenant_or_404(db, public_id=invite_data["tenant_public_id"])
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
    current_user: User,
    tenant_public_id: str,
    member_public_id: str,
) -> schemas.TenantMemberResponse:
    tenant    = await _get_tenant_or_404(db, public_id=tenant_public_id)
    caller_tu = await _get_membership_or_403(db, tenant_id=tenant.id, user_id=current_user.id)

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
    current_user: User,
    tenant_public_id: str,
    member_public_id: str,
) -> schemas.TenantMemberResponse:
    """
    Admin/owner suspends or reactivates a member within this tenant only.
    Suspended/deactivated members free up their seat immediately.
    Reactivating checks seat limit again before allowing.
    """
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    caller_tu = await _get_membership_or_403(
        db, tenant_id=tenant.id, user_id=current_user.id
    )

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

    if target_tu.user_id == current_user.id:
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
    current_user: User,
    tenant_public_id: str,
    member_public_id: str,
) -> schemas.RemoveMemberResponse:
    tenant    = await _get_tenant_or_404(db, public_id=tenant_public_id)
    caller_tu = await _get_membership_or_403(db, tenant_id=tenant.id, user_id=current_user.id)

    target_tu = await repo.get_tenant_user_by_public_id(db, public_id=member_public_id)
    if not target_tu or target_tu.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")

    is_self = target_tu.user_id == current_user.id
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