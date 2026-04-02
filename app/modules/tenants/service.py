# app/modules/tenants/service.py

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenants import repository as repo
from app.modules.tenants import schemas
from app.modules.users import repository as user_repo
from app.modules.tenants.models import Tenant, TenantUser
from app.modules.users.models import User
from app.core.enums import TenantStatus, TenantRole, UserStatus
from app.utils.jwt_utils import create_invite_token, decode_invite_token
from app.utils.hashing_utils import hash_password
from app.config.settings import get_settings

settings = get_settings()

INVITE_TTL_HOURS = 72


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
    Creates a new tenant and assigns the calling user as its primary owner.
    Called during company onboarding after the user has verified their email.

    Flow:
        1. Validate slug uniqueness
        2. Build Tenant via from_schema — status always forced to pending_plan
        3. Persist tenant + TenantUser atomically in one commit
    """

    # 1. Slug uniqueness
    if await repo.slug_exists(db, slug=payload.slug):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The slug '{payload.slug}' is already taken.",
        )

    # 2. from_schema maps all matching columns automatically.
    #    status override ensures the client can never set this themselves.
    tenant = Tenant.from_schema(
        payload,
        status=TenantStatus.PENDING_PLAN,
    )

    # 3. Persist tenant (flush only — commit comes after both rows are ready)
    tenant = await repo.create_tenant(db, tenant=tenant)

    # 4. Build owner membership directly — no extra repo wrapper needed
    db.add(TenantUser(
        tenant_id=tenant.id,
        user_id=owner.id,
        role=TenantRole.OWNER,
        is_primary_owner=True,
        joined_at=datetime.now(timezone.utc),
    ))

    # 5. Single commit — Tenant + TenantUser land atomically
    await db.commit()
    await db.refresh(tenant)

    return schemas.TenantResponse.model_validate(tenant)


async def get_my_tenant(
    db: AsyncSession,
    *,
    current_user: User,
    tenant_public_id: str,
) -> schemas.MyTenantContext:
    """
    Returns the calling user's role/context within a specific tenant.
    Raises 404 if tenant not found, 403 if user is not a member.
    """
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    tu = await _get_membership_or_403(db, tenant_id=tenant.id, user_id=current_user.id)

    return schemas.MyTenantContext(
        tenant=schemas.TenantSummary.model_validate(tenant),
        role=tu.role,
        is_owner=tu.is_primary_owner,
        joined_at=tu.joined_at,
    )


async def update_tenant(
    db: AsyncSession,
    *,
    payload: schemas.TenantUpdateRequest,
    current_user: User,
    tenant_public_id: str,
) -> schemas.TenantResponse:
    """Admin or owner can update tenant profile."""
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    tu = await _get_membership_or_403(db, tenant_id=tenant.id, user_id=current_user.id)

    if not tu.is_owner_or_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins and owners can update tenant details.",
        )

    # exclude_unset=True — only apply fields the caller actually sent
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
    """
    Super-admin only — manually change a tenant's status.
    Gate enforcement (super-admin auth check) happens in the API layer.
    """
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
    """Any tenant member can list other members."""
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    await _get_membership_or_403(db, tenant_id=tenant.id, user_id=current_user.id)

    members, total = await repo.list_tenant_members(
        db, tenant_id=tenant.id, role=role, skip=skip, limit=limit
    )

    return schemas.MemberListResponse(
        total=total,
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
    Admin/owner invites a new user to their tenant.

    Flow:
        1. Verify caller is admin or owner
        2. Gate 3 — seat limit check
        3. Check if email is already a member
        4. Sign an invite token (JWT with tenant + role + email)
        5. Send invite email  ← plug in your email service here
    """
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    tu = await _get_membership_or_403(db, tenant_id=tenant.id, user_id=current_user.id)

    # 1. Permission check
    if not tu.is_owner_or_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins and owners can invite users.",
        )

    # 2. Gate 3 — seat limit
    # TODO: Replace SEAT_LIMIT with plan.limits['max_users'] + addon_qty
    current_count = await repo.count_tenant_members(db, tenant_id=tenant.id)
    SEAT_LIMIT = 10  # placeholder
    if current_count >= SEAT_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Seat limit reached. Upgrade your plan to invite more users.",
        )

    # 3. Already a member?
    existing_user = await user_repo.get_user_by_email(db, email=payload.email)
    if existing_user:
        if await repo.is_member(db, tenant_id=tenant.id, user_id=existing_user.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This user is already a member of your team.",
            )

    # 4. Sign invite token
    expires_at = datetime.now(timezone.utc) + timedelta(hours=INVITE_TTL_HOURS)
    token = create_invite_token(
        tenant_public_id=tenant.public_id,
        email=payload.email,
        role=payload.role.value,
        invited_by_id=current_user.id,
        expires_at=expires_at,
    )

    # 5. TODO: plug in your email service
    # await email_service.send_invite(
    #     to=payload.email,
    #     inviter_name=current_user.full_name,
    #     tenant_name=tenant.name,
    #     invite_link=f"{settings.FRONTEND_URL}/invite/accept?token={token}",
    # )

    return schemas.InviteResponse(
        email=payload.email,
        role=payload.role,
        expires_at=expires_at,
    )


async def accept_invite(
    db: AsyncSession,
    *,
    payload: schemas.AcceptInviteRequest,
) -> schemas.AcceptInviteResponse:
    """
    Called by the invitee when they click the invite link.

    Flow:
        1. Decode + validate the invite token
        2. Resolve tenant
        3. Create or find the user — from_schema + overrides for new users
        4. Build TenantUser and commit atomically
    """

    # 1. Decode token
    try:
        token_data = decode_invite_token(payload.token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invite link.",
        )

    tenant        = await _get_tenant_or_404(db, public_id=token_data["tenant_public_id"])
    email         = token_data["email"]
    role          = TenantRole(token_data["role"])
    invited_by_id = token_data.get("invited_by_id")

    # 2. Create or fetch the user
    existing_user = await user_repo.get_user_by_email(db, email=email)

    if existing_user:
        user = existing_user
        if await repo.is_member(db, tenant_id=tenant.id, user_id=user.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You are already a member of this team.",
            )
    else:
        # New user — from_schema maps first_name, last_name, password from payload.
        # Overrides handle the fields that need transformation.
        user = await user_repo.create_user(
            db,
            payload=payload,
            overrides={
                "email":              email,
                "email_hash":         hashlib.sha256(email.lower().encode()).hexdigest(),
                "password_hash":      hash_password(payload.password),
                "status":             UserStatus.ACTIVE,       # skip OTP for invited users
                "email_verified_at":  datetime.now(timezone.utc),
            },
        )

    # 3. Create TenantUser membership
    db.add(TenantUser(
        tenant_id=tenant.id,
        user_id=user.id,
        role=role,
        invited_by=invited_by_id,
        joined_at=datetime.now(timezone.utc),
    ))

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
    """Owner/admin can change a member's role. Cannot change the owner's role."""
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


async def remove_member(
    db: AsyncSession,
    *,
    current_user: User,
    tenant_public_id: str,
    member_public_id: str,
) -> schemas.RemoveMemberResponse:
    """
    Admin/owner removes a member.
    Members can also remove themselves (leave the tenant).
    The primary owner cannot be removed.
    """
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
    db: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
) -> TenantUser:
    tu = await repo.get_tenant_user(db, tenant_id=tenant_id, user_id=user_id)
    if not tu:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this tenant.",
        )
    return tu


def _build_member_response(tu: TenantUser) -> schemas.TenantMemberResponse:
    """
    Flattens TenantUser + User into TenantMemberResponse.
    Requires TenantUser.user relationship to be loaded.
    """
    user = tu.user
    return schemas.TenantMemberResponse(
        public_id=tu.public_id,
        role=tu.role,
        is_primary_owner=tu.is_primary_owner,
        joined_at=tu.joined_at,
        created_at=tu.created_at,
        user_public_id=user.public_id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        avatar_url=user.avatar_url,
    )