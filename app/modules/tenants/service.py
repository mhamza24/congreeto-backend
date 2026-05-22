from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SlugExistError
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
from app.modules.audit import repository as audit
from app.modules.billing import repository as billing_repo
from app.core.response import PaginationMeta
import logging

logger = logging.getLogger(__name__)

settings = get_settings()

# Sourced from Settings so the entire invite lifecycle (email TTL copy,
# OTP expiry, resend window) can be tuned in one place.
INVITE_TTL_HOURS = settings.TENANT_INVITE_TTL_HOURS


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
    if sub and sub.plan:
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
    logger.info("[tenants] create_tenant attempt slug=%s owner=%s", payload.slug, owner.public_id)

    # Billing gate — owner must have an active UserSubscription before creating a workspace
    user_sub = await billing_repo.get_active_user_subscription(db, user_id=owner.id)
    if not user_sub or not user_sub.is_active:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="A subscription is required to create a workspace. Please select a plan.",
        )

    max_tenants  = user_sub.plan.get_limit("max_tenants", 1)
    owned_count  = await repo.count_owned_tenants(db, user_id=owner.id)
    if owned_count >= max_tenants:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Your plan allows a maximum of {max_tenants} workspace(s). "
                "Upgrade your plan to create more."
            ),
        )

    if await repo.slug_exists(db, slug=payload.slug):
        logger.warning("[tenants] create_tenant slug conflict slug=%s", payload.slug)
        raise SlugExistError()

    # Tenant starts ACTIVE immediately — owner has already paid
    tenant = Tenant.from_schema(payload, status=TenantStatus.ACTIVE)
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

    await audit.write(
        db,
        entity_type="tenants",
        action=audit.CREATE,
        tenant_id=tenant.id,
        user_id=owner.id,
        entity_id=tenant.id,
        diff={"after": {"slug": tenant.slug, "name": tenant.name}},
    )

    await db.commit()
    await db.refresh(tenant)
    logger.info("[tenants] tenant created public_id=%s slug=%s owner=%s", tenant.public_id, tenant.slug, owner.public_id)
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
        logger.warning("[tenants] update_tenant forbidden tenant=%s caller_role=%s", tenant.public_id, caller_tu.role)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins and owners can update tenant details.",
        )

    changed = payload.model_dump(exclude_unset=True)
    changed_fields = list(changed.keys())
    for field, value in changed.items():
        setattr(tenant, field, value)

    await audit.write(
        db,
        entity_type="tenants",
        action=audit.UPDATE,
        tenant_id=tenant.id,
        user_id=caller_tu.user_id,
        entity_id=tenant.id,
        diff={"after": {k: str(v) for k, v in changed.items()}},
    )

    await db.commit()
    await db.refresh(tenant)
    logger.info("[tenants] tenant updated tenant=%s fields=%s", tenant.public_id, changed_fields)
    return schemas.TenantResponse.model_validate(tenant)


async def update_tenant_status(
    db: AsyncSession,
    *,
    payload: schemas.TenantStatusUpdateRequest,
    tenant_public_id: str,
) -> schemas.TenantResponse:
    """Super-admin only."""
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    old_status = tenant.status
    tenant.status = payload.status

    action = audit.SUSPEND if str(payload.status) == "suspended" else audit.RESTORE
    await audit.write(
        db,
        entity_type="tenants",
        action=action,
        tenant_id=tenant.id,
        entity_id=tenant.id,
        diff={"before": {"status": str(old_status)}, "after": {"status": str(payload.status)}},
    )

    await db.commit()
    await db.refresh(tenant)
    logger.info("[tenants] tenant status changed tenant=%s old=%s new=%s", tenant.public_id, old_status, payload.status)
    return schemas.TenantResponse.model_validate(tenant)


# =============================================================================
# MEMBER OPERATIONS
# =============================================================================


async def list_members(
    db: AsyncSession,
    *,
    tenant: Tenant,
    caller_tu: Optional[TenantUser] = None,
    caller_user=None,
    role: Optional[TenantRole] = None,
    skip: int = 0,
    limit: int = 50,
) -> schemas.MemberListResponse:
    members, total = await repo.list_tenant_members(
        db, tenant_id=tenant.id, role=role, skip=skip, limit=limit
    )
    seat_info = await _get_seat_info(db, tenant_id=tenant.id)

    member_responses = [_build_member_response(m) for m in members if m.user is not None]

    # Include legacy pending invites that have no TenantUser row yet (pre-fix data).
    # New invites already create a TenantUser(status=INVITED), so this only catches
    # invites sent before that fix was deployed.
    pending_invites = await repo.get_pending_invites_without_membership(
        db, tenant_id=tenant.id
    )
    pending_count = 0
    for invite in pending_invites:
        if invite.invitee is None:
            continue
        if role and invite.role != role:
            continue
        member_responses.append(_build_pending_invite_response(invite))
        pending_count += 1

    # Build the caller's own membership entry so the frontend knows "which one is me"
    me = None
    if caller_tu is not None and caller_user is not None:
        me = schemas.TenantMemberResponse(
            public_id=str(caller_tu.public_id),
            role=caller_tu.role,
            status=caller_tu.status,
            is_primary_owner=caller_tu.is_primary_owner,
            joined_at=caller_tu.joined_at,
            created_at=caller_tu.created_at,
            user_public_id=caller_user.public_id,
            user_last_login=caller_user.last_login_at,
            email=caller_user.email,
            first_name=caller_user.first_name,
            last_name=caller_user.last_name,
            avatar_url=caller_user.avatar_url,
        )

    return schemas.MemberListResponse(
        total=total + pending_count,
        **seat_info,
        me=me,
        members=member_responses,
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

    Resend rate-limit (per email+tenant, rolling 24h window):
      1st send  → no delay
      2nd send  → must wait 30 minutes after the 1st
      3rd send  → must wait 2 hours after the 2nd
      4th send+ → locked for 24 hours from the 1st send in the window
    """
    tu = caller_tu
    if not tu.is_owner_or_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins and owners can invite users.",
        )

    logger.info("[tenants] invite_user attempt tenant=%s email=%s role=%s", tenant.public_id, payload.email, payload.role)
    # Gate 3 — seat limit check
    seat_info = await _get_seat_info(db, tenant_id=tenant.id)
    if seat_info["seats_remaining"] <= 0:
        logger.warning("[tenants] invite_user seat limit reached tenant=%s used=%d total=%d", tenant.public_id, seat_info["seats_used"], seat_info["seats_total"])
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

    # Resend rate-limit check
    recent_invites = await repo.get_invites_last_24h(
        db, tenant_id=tenant.id, invitee_user_id=invitee.id
    )
    _check_invite_rate_limit(recent_invites)

    # Create OTP record in DB (same table used by email verification)
    # expires_in_minutes = 72h * 60 = 4320 min
    raw_otp = await auth_repo.create_otp(
        db,
        user_id            = invitee.id,
        purpose            = OTPPurpose.TENANT_INVITE,
        expires_in_minutes = INVITE_TTL_HOURS * 60,
    )

    # Store invite metadata in DB (tenant, role, invited_by) — replaces Redis
    otp_record = await auth_repo.get_active_otp(
        db, user_id=invitee.id, purpose=OTPPurpose.TENANT_INVITE
    )
    await repo.create_invite(
        db,
        tenant_id=tenant.id,
        invitee_user_id=invitee.id,
        invited_by_user_id=caller_tu.user_id,
        role=payload.role,
        otp_id=otp_record.id,
        expires_at=expires_at,
    )

    # Create a TenantUser row immediately so the invitee appears in the member list
    # with status=INVITED before they accept.
    existing_tu = await repo.get_tenant_user(db, tenant_id=tenant.id, user_id=invitee.id)
    if not existing_tu:
        db.add(
            TenantUser(
                tenant_id  = tenant.id,
                user_id    = invitee.id,
                role       = payload.role,
                invited_by = caller_tu.user_id,
                status     = TenantUserStatus.INVITED,
            )
        )

    # ── Audit log — user invited ──────────────────────────────────────────────
    await audit.write(
        db,
        entity_type="tenant_invites",
        action=audit.INVITE,
        tenant_id=tenant.id,
        user_id=caller_tu.user_id,
        entity_id=invitee.id,
        diff={"after": {"email": payload.email, "role": payload.role.value}},
    )

    await db.commit()

    invite_link = f"{settings.FRONTEND_URL}/accept-invite?code={raw_otp}"
    celery_task = background_tasks.send_invite_email_task.delay(
        to           = payload.email,
        first_name   = invitee.first_name or payload.email.split("@")[0],
        inviter_name = caller_tu.user.full_name if hasattr(caller_tu, "user") and caller_tu.user else "Team",
        tenant_name  = tenant.name,
        invite_link  = invite_link,
        role         = payload.role.value,
    )
    logger.info("[tenants] invite sent tenant=%s email=%s role=%s task=%s", tenant.public_id, payload.email, payload.role, celery_task.id)

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
    logger.info("[tenants] accept_invite attempt")
    # 1. Look up OTP record by hash — no Redis needed
    otp_hash = hash_otp(payload.code)
    otp_record = await auth_repo.get_active_otp_by_hash(
        db, code_hash=otp_hash, purpose=OTPPurpose.TENANT_INVITE
    )
    if otp_record is None:
        logger.warning("[tenants] accept_invite invalid or expired code")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invite link.",
        )

    # 2. Load invite metadata from DB
    invite = await repo.get_invite_by_otp_id(db, otp_id=otp_record.id)
    if invite is None or invite.consumed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invite link.",
        )

    user_id       = invite.invitee_user_id
    role          = invite.role
    invited_by_id = invite.invited_by_user_id

    # 3. Verify OTP — marks consumed_at on success, increments attempts on failure
    is_valid = await auth_repo.verify_otp(db, record=otp_record, raw_code=payload.code)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invite link.",
        )

    # 4. Mark invite consumed
    await repo.consume_invite(db, invite=invite)

    # 5. Load tenant, verify it's still active, and re-check seat limit at acceptance time
    tenant = await repo.get_tenant_by_id(db, id=invite.tenant_id)
    if tenant is None or tenant.status in (TenantStatus.SUSPENDED, TenantStatus.CANCELLED):
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

    # 6. Load the pre-created invited user
    user = await user_repo.get_user_by_id(db, id=user_id)

    # 7. If user is still in INVITED state, activate them with submitted profile
    if user.status == UserStatus.INVITED:
        user.first_name        = payload.first_name
        user.last_name         = payload.last_name
        user.password_hash     = hash_password(payload.password)
        user.status            = UserStatus.ACTIVE
        user.email_verified_at = datetime.now(timezone.utc)
        await db.flush()

    # 8. Activate the pre-created TenantUser row (created at invite time)
    existing_tu = await repo.get_tenant_user(db, tenant_id=tenant.id, user_id=user.id)
    if existing_tu:
        if existing_tu.status == TenantUserStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You are already a member of this team.",
            )
        existing_tu.status    = TenantUserStatus.ACTIVE
        existing_tu.joined_at = datetime.now(timezone.utc)
    else:
        # Fallback: no pre-created row (e.g. legacy invites), create one now
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

    # ── Audit log — invite accepted / member joined ───────────────────────────
    await audit.write(
        db,
        entity_type="tenant_users",
        action=audit.CREATE,
        tenant_id=tenant.id,
        user_id=user.id,
        entity_id=user.id,
        diff={"after": {"role": str(role), "tenant_public_id": tenant.public_id}},
    )

    await db.commit()
    logger.info("[tenants] invite accepted user=%s tenant=%s role=%s", user.public_id, tenant.public_id, role)
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

    old_role = target_tu.role
    target_tu.role = payload.role

    await audit.write(
        db,
        entity_type="tenant_users",
        action=audit.UPDATE,
        tenant_id=tenant.id,
        user_id=caller_tu.user_id,
        entity_id=target_tu.user_id,
        diff={"before": {"role": str(old_role)}, "after": {"role": str(payload.role)}},
    )

    await db.commit()
    await db.refresh(target_tu)
    logger.info("[tenants] member role changed tenant=%s member=%s old=%s new=%s", tenant.public_id, member_public_id, old_role, payload.role)
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
            logger.warning("[tenants] update_member_status seat limit reached tenant=%s member=%s used=%d total=%d", tenant.public_id, member_public_id, seat_info["seats_used"], seat_info["seats_total"])
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"Cannot reactivate member. Seat limit reached "
                    f"({seat_info['seats_used']}/{seat_info['seats_total']} seats used). "
                    "Purchase additional seats to reactivate this member."
                ),
            )

    old_status = target_tu.status
    target_tu.status = payload.status

    await audit.write(
        db,
        entity_type="tenant_users",
        action=audit.UPDATE,
        tenant_id=tenant.id,
        user_id=current_user_id,
        entity_id=target_tu.user_id,
        diff={"before": {"status": str(old_status)}, "after": {"status": str(payload.status)}},
    )

    await db.commit()
    await db.refresh(target_tu)
    logger.info("[tenants] member status changed tenant=%s member=%s old=%s new=%s", tenant.public_id, member_public_id, old_status, payload.status)
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

    removed_user_id = target_tu.user_id
    removed_role = str(target_tu.role)

    await audit.write(
        db,
        entity_type="tenant_users",
        action=audit.DELETE,
        tenant_id=tenant.id,
        user_id=current_user_id,
        entity_id=removed_user_id,
        diff={"before": {"role": removed_role, "member_public_id": member_public_id}},
    )

    await db.delete(target_tu)
    await db.commit()
    logger.info("[tenants] member removed tenant=%s member=%s by_self=%s", tenant.public_id, member_public_id, is_self)
    return schemas.RemoveMemberResponse()


# =============================================================================
# PRIVATE HELPERS
# =============================================================================


def _check_invite_rate_limit(recent_invites: list) -> None:
    """
    Enforces invite resend rate-limiting based on sends in the last 24 hours.

    Rules (rolling 24h window):
      count == 0 → allow (first send)
      count == 1 → allow only if last send was > 30 minutes ago
      count == 2 → allow only if last send was > 2 hours ago
      count >= 3 → locked; tell caller when 24h window resets
    """
    count = len(recent_invites)
    if count == 0:
        return

    now = datetime.now(timezone.utc)
    # recent_invites is ordered most-recent first
    last_sent = recent_invites[0].sent_at

    if count >= 3:
        # Locked until the oldest of the 3 sends ages out of the 24h window
        oldest_sent = recent_invites[-1].sent_at
        lock_until = oldest_sent + timedelta(hours=24)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Invite limit reached (3 sends in 24 hours). "
                f"You can send again after {lock_until.strftime('%Y-%m-%d %H:%M UTC')}."
            ),
        )

    if count == 2:
        delay = timedelta(hours=2)
    else:  # count == 1
        delay = timedelta(minutes=30)

    earliest_resend = last_sent + delay
    if now < earliest_resend:
        wait_minutes = int((earliest_resend - now).total_seconds() / 60) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Please wait before resending. "
                f"You can resend after {earliest_resend.strftime('%Y-%m-%d %H:%M UTC')} "
                f"({wait_minutes} minute{'s' if wait_minutes != 1 else ''} remaining)."
            ),
        )

# =============================================================================
# ADMIN OPERATIONS — SUPER ADMIN ONLY
# =============================================================================


async def admin_update_tenant(
    db: AsyncSession,
    *,
    payload: schemas.TenantUpdateRequest,
    tenant_public_id: str,
) -> schemas.TenantResponse:
    """Super-admin can edit any tenant's profile directly, without being a member."""
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    changed = payload.model_dump(exclude_unset=True)
    for field, value in changed.items():
        setattr(tenant, field, value)

    await audit.write(
        db,
        entity_type="tenants",
        action=audit.UPDATE,
        tenant_id=tenant.id,
        entity_id=tenant.id,
        diff={"after": {k: str(v) for k, v in changed.items()}},
    )

    await db.commit()
    await db.refresh(tenant)
    logger.info("[tenants] admin updated tenant=%s fields=%s", tenant_public_id, list(changed.keys()))
    return schemas.TenantResponse.model_validate(tenant)


async def admin_delete_tenant(
    db: AsyncSession,
    *,
    tenant_public_id: str,
) -> None:
    """Super-admin soft-deletes a tenant. All data is retained but access is blocked."""
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)

    await audit.write(
        db,
        entity_type="tenants",
        action=audit.DELETE,
        tenant_id=tenant.id,
        entity_id=tenant.id,
        diff={"before": {"name": tenant.name, "slug": tenant.slug, "status": str(tenant.status)}},
    )

    await repo.soft_delete_tenant(db, tenant=tenant)
    await db.commit()
    logger.info("[tenants] tenant soft-deleted tenant=%s", tenant.public_id)


async def admin_update_member_role(
    db: AsyncSession,
    *,
    tenant_public_id: str,
    member_public_id: str,
    payload: schemas.UpdateMemberRoleRequest,
) -> schemas.TenantMemberResponse:
    """Super-admin changes a member's role, bypassing the caller_tu ownership check."""
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    target_tu = await repo.get_tenant_user_by_public_id(db, public_id=member_public_id)
    if not target_tu or target_tu.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    if target_tu.is_primary_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot change the primary owner's role.",
        )
    old_role = target_tu.role
    target_tu.role = payload.role

    await audit.write(
        db,
        entity_type="tenant_users",
        action=audit.UPDATE,
        tenant_id=tenant.id,
        entity_id=target_tu.user_id,
        diff={"before": {"role": str(old_role)}, "after": {"role": str(payload.role)}},
    )

    await db.commit()
    await db.refresh(target_tu)
    logger.info("[tenants] admin role changed tenant=%s member=%s old=%s new=%s", tenant_public_id, member_public_id, old_role, payload.role)
    return _build_member_response(target_tu)


async def admin_update_member_status(
    db: AsyncSession,
    *,
    tenant_public_id: str,
    member_public_id: str,
    payload: schemas.UpdateMemberStatusRequest,
) -> schemas.TenantMemberResponse:
    """Super-admin suspends or reactivates a member, bypassing seat-limit enforcement."""
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    target_tu = await repo.get_tenant_user_by_public_id(db, public_id=member_public_id)
    if not target_tu or target_tu.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    if target_tu.is_primary_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot change the primary owner's status.",
        )
    old_status = target_tu.status
    target_tu.status = payload.status

    await audit.write(
        db,
        entity_type="tenant_users",
        action=audit.UPDATE,
        tenant_id=tenant.id,
        entity_id=target_tu.user_id,
        diff={"before": {"status": str(old_status)}, "after": {"status": str(payload.status)}},
    )

    await db.commit()
    await db.refresh(target_tu)
    logger.info("[tenants] admin status changed tenant=%s member=%s old=%s new=%s", tenant_public_id, member_public_id, old_status, payload.status)
    return _build_member_response(target_tu)


async def admin_remove_member(
    db: AsyncSession,
    *,
    tenant_public_id: str,
    member_public_id: str,
) -> schemas.RemoveMemberResponse:
    """Super-admin removes any member from a tenant without role restrictions."""
    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)
    target_tu = await repo.get_tenant_user_by_public_id(db, public_id=member_public_id)
    if not target_tu or target_tu.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    if target_tu.is_primary_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The primary owner cannot be removed from the tenant.",
        )

    await audit.write(
        db,
        entity_type="tenant_users",
        action=audit.DELETE,
        tenant_id=tenant.id,
        entity_id=target_tu.user_id,
        diff={"before": {"role": str(target_tu.role), "member_public_id": member_public_id}},
    )

    await db.delete(target_tu)
    await db.commit()
    logger.info("[tenants] admin removed member tenant=%s member=%s", tenant_public_id, member_public_id)
    return schemas.RemoveMemberResponse()


async def admin_list_tenants(
    db: AsyncSession,
    *,
    status: Optional[TenantStatus] = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[schemas.AdminTenantListResponse, PaginationMeta]:
    tenants, total = await repo.list_tenants(db, status=status, skip=skip, limit=limit)

    items = []
    for tenant in tenants:
        member_count = await repo.count_active_members(db, tenant_id=tenant.id)
        sub = await billing_repo.get_active_subscription(db, tenant_id=tenant.id)
        items.append(
            schemas.AdminTenantListItem(
                public_id=tenant.public_id,
                name=tenant.name,
                slug=tenant.slug,
                status=tenant.status,
                industry=tenant.industry,
                created_at=tenant.created_at,
                updated_at=tenant.updated_at,
                member_count=member_count,
                plan_name=sub.plan.name if sub else None,
                subscription_status=sub.status.value if sub else None,
            )
        )

    meta = PaginationMeta(
        total=total,
        limit=limit,
        offset=skip,
        has_next=(skip + limit) < total,
        has_prev=skip > 0,
    )
    return schemas.AdminTenantListResponse(tenants=items), meta


async def admin_get_tenant_detail(
    db: AsyncSession,
    *,
    tenant_public_id: str,
) -> schemas.AdminTenantDetail:
    import asyncio

    tenant = await _get_tenant_or_404(db, public_id=tenant_public_id)

    # Run all independent aggregation queries concurrently
    (
        sub,
        addons,
        member_counts,
        chatbot_counts,
        doc_counts,
        pending_tasks,
    ) = await asyncio.gather(
        billing_repo.get_active_subscription(db, tenant_id=tenant.id),
        billing_repo.list_tenant_addons(db, tenant_id=tenant.id),
        repo.count_members_by_status(db, tenant_id=tenant.id),
        repo.count_chatbots_by_status(db, tenant_id=tenant.id),
        repo.count_documents_by_status(db, tenant_id=tenant.id),
        repo.count_pending_crawl_jobs(db, tenant_id=tenant.id),
    )

    # Members — full list (no caller context needed for super-admin)
    members, _ = await repo.list_tenant_members(db, tenant_id=tenant.id, skip=0, limit=200)
    member_responses = [_build_member_response(m) for m in members if m.user is not None]

    # Usage for current month
    from datetime import datetime, timezone
    period_month = datetime.now(timezone.utc).strftime("%Y-%m")
    usage_records = await billing_repo.get_all_usage_for_period(
        db, tenant_id=tenant.id, period_month=period_month
    )

    # Build subscription detail
    sub_detail = None
    if sub:
        sub_detail = schemas.AdminSubscriptionInfo(
            public_id=sub.public_id,
            plan_name=sub.plan.name,
            plan_slug=sub.plan.slug,
            status=sub.status.value,
            billing_interval=sub.plan.billing_interval.value,
            price_aud_cents=sub.plan.price_aud_cents,
            currency=sub.currency,
            current_period_start=sub.current_period_start,
            current_period_end=sub.current_period_end,
            trial_ends_at=sub.trial_ends_at,
            cancel_at_period_end=sub.cancel_at_period_end,
            cancelled_at=sub.cancelled_at,
            notes=sub.notes,
        )

    # Build addon list
    addon_details = [
        schemas.AdminAddonInfo(
            addon_name=tas.addon.name,
            addon_type=tas.addon.type.value,
            quantity=tas.quantity,
            status=tas.status.value,
        )
        for tas in addons
    ]

    # Build usage list
    usage_items = [
        schemas.AdminUsageItem(
            metric=u.metric.value,
            quantity=u.quantity,
            period_month=u.period_month,
        )
        for u in usage_records
    ]

    return schemas.AdminTenantDetail(
        public_id=tenant.public_id,
        name=tenant.name,
        slug=tenant.slug,
        industry=tenant.industry,
        status=tenant.status,
        settings=tenant.settings,
        trial_ends_at=tenant.trial_ends_at,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        subscription=sub_detail,
        addons=addon_details,
        current_usage=usage_items,
        member_summary=schemas.AdminMemberSummary(**member_counts),
        members=member_responses,
        chatbot_summary=schemas.AdminChatbotSummary(**chatbot_counts),
        document_summary=schemas.AdminDocumentSummary(**doc_counts),
        pending_tasks=schemas.AdminPendingTasks(**pending_tasks),
    )


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


def _build_pending_invite_response(invite) -> schemas.TenantMemberResponse:
    """Build a member response for a legacy pending invite (no TenantUser row yet)."""
    user = invite.invitee
    return schemas.TenantMemberResponse(
        public_id=str(invite.public_id),
        role=invite.role,
        status=TenantUserStatus.INVITED,
        is_primary_owner=False,
        joined_at=None,
        created_at=invite.sent_at,
        user_public_id=user.public_id,
        user_last_login=user.last_login_at,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        avatar_url=user.avatar_url,
    )


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


# =============================================================================
# ONBOARDING
# =============================================================================

async def get_onboarding_status(
    db: AsyncSession,
    *,
    tenant: Tenant,
    membership: TenantUser,
    current_user: User,
    subscription,
) -> schemas.OnboardingResponse | schemas.TenantOverviewResponse:
    """
    For owner/admin: return a checklist of setup steps with completion state.
    For agent/viewer: return a brief tenant overview instead.
    """
    from app.modules.chatbot import repository as chatbot_repo
    from sqlalchemy import select, func
    from app.modules.chatbot.models import ChatbotConfig
    from app.core.enums import ChatbotStatus

    # ── Non-owner members get an overview, not a checklist ───────────────────
    if membership.role in (TenantRole.AGENT, TenantRole.VIEWER):
        total_chatbots = await chatbot_repo.count_chatbots_for_tenant(db, tenant_id=tenant.id)
        total_documents = await chatbot_repo.count_documents_for_tenant(db, tenant_id=tenant.id)

        active_result = await db.execute(
            select(func.count()).select_from(ChatbotConfig).where(
                ChatbotConfig.tenant_id == tenant.id,
                ChatbotConfig.status == ChatbotStatus.ACTIVE,
            )
        )
        active_chatbots = active_result.scalar_one()

        plan_name = subscription.plan.name if subscription and subscription.plan else None

        logger.debug("[tenants] onboarding overview tenant=%s user=%s role=%s", tenant.public_id, current_user.public_id, membership.role)
        return schemas.TenantOverviewResponse(
            role=membership.role.value,
            tenant_name=tenant.name,
            tenant_public_id=tenant.public_id,
            plan_name=plan_name,
            total_chatbots=total_chatbots,
            active_chatbots=active_chatbots,
            total_documents=total_documents,
            member_since=membership.joined_at,
        )

    # ── Owner/admin: compute step completion ─────────────────────────────────
    total_chatbots = await chatbot_repo.count_chatbots_for_tenant(db, tenant_id=tenant.id)
    total_documents = await chatbot_repo.count_documents_for_tenant(db, tenant_id=tenant.id)

    # Has any chatbot been configured (system_prompt_template rendered)?
    configured_result = await db.execute(
        select(func.count()).select_from(ChatbotConfig).where(
            ChatbotConfig.tenant_id == tenant.id,
            ChatbotConfig.system_prompt_template.isnot(None),
        )
    )
    configured_chatbots = configured_result.scalar_one()

    active_result = await db.execute(
        select(func.count()).select_from(ChatbotConfig).where(
            ChatbotConfig.tenant_id == tenant.id,
            ChatbotConfig.status == ChatbotStatus.ACTIVE,
        )
    )
    active_chatbots = active_result.scalar_one()

    steps = [
        schemas.OnboardingStep(
            key="email_verified",
            label="Verify your email address",
            completed=current_user.email_verified_at is not None,
        ),
        schemas.OnboardingStep(
            key="plan_selected",
            label="Select a subscription plan",
            completed=tenant.status != TenantStatus.PENDING_PLAN,
        ),
        schemas.OnboardingStep(
            key="tenant_created",
            label="Register your company",
            completed=True,  # they're on this endpoint — tenant exists
        ),
        schemas.OnboardingStep(
            key="chatbot_configured",
            label="Configure your chatbot",
            completed=configured_chatbots > 0,
        ),
        schemas.OnboardingStep(
            key="content_uploaded",
            label="Upload documents or connect a data source",
            completed=total_documents > 0,
        ),
        schemas.OnboardingStep(
            key="chatbot_activated",
            label="Activate your chatbot",
            completed=active_chatbots > 0,
        ),
    ]

    completed_count = sum(1 for s in steps if s.completed)
    logger.info("[tenants] onboarding status tenant=%s user=%s completed=%d/%d", tenant.public_id, current_user.public_id, completed_count, len(steps))

    return schemas.OnboardingResponse(
        role=membership.role.value,
        steps=steps,
        completed_count=completed_count,
        total_steps=len(steps),
    )