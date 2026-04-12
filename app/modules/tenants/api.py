from __future__ import annotations

import logging
from typing import Optional, Annotated

import sentry_sdk
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse, PagedApiResponse
from app.dependencies.auth import get_current_user, require_superadmin
from app.dependencies.tenant import TenantContext, get_tenant_context, require_write
from app.core.database import get_db
from app.dependencies.user import get_verified_user
from app.modules.tenants import schemas, service
from app.core.enums import TenantRole, TenantStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants", tags=["Tenants"])

DBDep = Annotated[AsyncSession, Depends(get_db)]


# =============================================================================
# TENANT ENDPOINTS
# =============================================================================

@router.post(
    "/",
    response_model=ApiResponse[schemas.TenantResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tenant (company registration)",
)
async def create_tenant(
    payload: schemas.TenantCreateRequest,
    db: DBDep,
    current_user=Depends(get_verified_user),
) -> ApiResponse[schemas.TenantResponse]:
    try:
        result = await service.create_tenant(db, payload=payload, owner=current_user)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error creating tenant")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create tenant. Please try again later.",
        )
    return ApiResponse(success=True, message="Tenant created successfully.", data=result)


@router.get(
    "/me",
    response_model=ApiResponse[schemas.UserTenantsResponse],
    status_code=status.HTTP_200_OK,
    summary="Get all tenants the current user belongs to",
)
async def get_my_tenants(
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.UserTenantsResponse]:
    try:
        result = await service.get_my_tenants(db, current_user=current_user)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error fetching user tenants")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch tenants. Please try again later.",
        )
    return ApiResponse(success=True, message="Tenants fetched successfully.", data=result)


@router.get(
    "/{tenant_public_id}/onboarding",
    response_model=ApiResponse[schemas.OnboardingResponse | schemas.TenantOverviewResponse],
    status_code=status.HTTP_200_OK,
    summary="Get onboarding checklist (owner/admin) or tenant overview (agent/viewer)",
)
async def get_onboarding(
    db: DBDep,
    ctx: TenantContext = Depends(get_tenant_context),
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.OnboardingResponse | schemas.TenantOverviewResponse]:
    try:
        result = await service.get_onboarding_status(
            db,
            tenant=ctx.tenant,
            membership=ctx.membership,
            current_user=current_user,
            subscription=ctx.subscription,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error fetching onboarding status tenant=%s", ctx.tenant.public_id)
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch onboarding status. Please try again later.",
        )
    return ApiResponse(success=True, message="Onboarding status fetched.", data=result)


@router.get(
    "/{tenant_public_id}",
    response_model=ApiResponse[schemas.MyTenantContext],
    status_code=status.HTTP_200_OK,
    summary="Get your context within a tenant",
)
async def get_my_tenant(
    db: DBDep,
    ctx: TenantContext = Depends(get_tenant_context),
) -> ApiResponse[schemas.MyTenantContext]:
    try:
        result = await service.get_my_tenant(
            db, current_user=ctx.membership.user_id, tenant_public_id=ctx.tenant.public_id,
            preloaded_tenant=ctx.tenant, preloaded_tu=ctx.membership,
            preloaded_sub=ctx.subscription,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error fetching tenant context")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch tenant. Please try again later.",
        )
    return ApiResponse(success=True, message="Tenant fetched successfully.", data=result)


@router.patch(
    "/{tenant_public_id}",
    response_model=ApiResponse[schemas.TenantResponse],
    status_code=status.HTTP_200_OK,
    summary="Update tenant profile (admin/owner only)",
)
async def update_tenant(
    payload: schemas.TenantUpdateRequest,
    db: DBDep,
    ctx: TenantContext = Depends(get_tenant_context),
) -> ApiResponse[schemas.TenantResponse]:
    require_write(ctx)
    try:
        result = await service.update_tenant(
            db, payload=payload, tenant=ctx.tenant, caller_tu=ctx.membership,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error updating tenant")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update tenant. Please try again later.",
        )
    return ApiResponse(success=True, message="Tenant updated successfully.", data=result)


@router.patch(
    "/{tenant_public_id}/status",
    response_model=ApiResponse[schemas.TenantResponse],
    status_code=status.HTTP_200_OK,
    summary="Change tenant status (super-admin only)",
)
async def update_tenant_status(
    tenant_public_id: str,
    payload: schemas.TenantStatusUpdateRequest,
    db: DBDep,
    _=Depends(require_superadmin),
) -> ApiResponse[schemas.TenantResponse]:
    try:
        result = await service.update_tenant_status(
            db, payload=payload, tenant_public_id=tenant_public_id
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error updating tenant status")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update tenant status. Please try again later.",
        )
    return ApiResponse(success=True, message="Tenant status updated.", data=result)


# =============================================================================
# MEMBER ENDPOINTS
# =============================================================================

@router.get(
    "/{tenant_public_id}/members",
    response_model=ApiResponse[schemas.MemberListResponse],
    status_code=status.HTTP_200_OK,
    summary="List all members of a tenant",
)
async def list_members(
    db: DBDep,
    ctx: TenantContext = Depends(get_tenant_context),
    current_user=Depends(get_current_user),
    role: Optional[TenantRole] = Query(None, description="Filter by role"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> ApiResponse[schemas.MemberListResponse]:
    try:
        result = await service.list_members(
            db, tenant=ctx.tenant, caller_tu=ctx.membership,
            caller_user=current_user, role=role, skip=skip, limit=limit,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error listing members")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch members. Please try again later.",
        )
    return ApiResponse(success=True, message="Members fetched successfully.", data=result)


@router.post(
    "/{tenant_public_id}/members/invite",
    response_model=ApiResponse[schemas.InviteResponse],
    status_code=status.HTTP_200_OK,
    summary="Invite a user to the tenant (admin/owner only)",
)
async def invite_user(
    payload: schemas.InviteUserRequest,
    db: DBDep,
    ctx: TenantContext = Depends(get_tenant_context),
) -> ApiResponse[schemas.InviteResponse]:
    require_write(ctx)
    try:
        result = await service.invite_user(
            db, payload=payload, tenant=ctx.tenant, caller_tu=ctx.membership,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error sending invite")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not send invite. Please try again later.",
        )
    return ApiResponse(success=True, message="Invitation sent successfully.", data=result)


@router.post(
    "/invite/accept",
    response_model=ApiResponse[schemas.AcceptInviteResponse],
    status_code=status.HTTP_200_OK,
    summary="Accept a team invite",
)
async def accept_invite(
    payload: schemas.AcceptInviteRequest,
    db: DBDep,
) -> ApiResponse[schemas.AcceptInviteResponse]:
    try:
        result = await service.accept_invite(db, payload=payload)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error accepting invite")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process invite. Please try again later.",
        )
    return ApiResponse(success=True, message="Invitation accepted. Welcome aboard.", data=result)


@router.patch(
    "/{tenant_public_id}/members/{member_public_id}/role",
    response_model=ApiResponse[schemas.TenantMemberResponse],
    status_code=status.HTTP_200_OK,
    summary="Change a member's role (admin/owner only)",
)
async def update_member_role(
    member_public_id: str,
    payload: schemas.UpdateMemberRoleRequest,
    db: DBDep,
    ctx: TenantContext = Depends(get_tenant_context),
) -> ApiResponse[schemas.TenantMemberResponse]:
    require_write(ctx)
    try:
        result = await service.update_member_role(
            db, payload=payload, caller_tu=ctx.membership,
            tenant=ctx.tenant, member_public_id=member_public_id,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error updating member role")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update member role. Please try again later.",
        )
    return ApiResponse(success=True, message="Member role updated.", data=result)


@router.patch(
    "/{tenant_public_id}/members/{member_public_id}/status",
    response_model=ApiResponse[schemas.TenantMemberResponse],
    status_code=status.HTTP_200_OK,
    summary="Suspend or reactivate a member (admin/owner only)",
)
async def update_member_status(
    member_public_id: str,
    payload: schemas.UpdateMemberStatusRequest,
    db: DBDep,
    ctx: TenantContext = Depends(get_tenant_context),
) -> ApiResponse[schemas.TenantMemberResponse]:
    require_write(ctx)
    try:
        result = await service.update_member_status(
            db, payload=payload, caller_tu=ctx.membership, current_user_id=ctx.membership.user_id,
            tenant=ctx.tenant, member_public_id=member_public_id,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error updating member status")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update member status. Please try again later.",
        )
    return ApiResponse(success=True, message="Member status updated.", data=result)


@router.delete(
    "/{tenant_public_id}/members/{member_public_id}",
    response_model=ApiResponse[schemas.RemoveMemberResponse],
    status_code=status.HTTP_200_OK,
    summary="Remove a member from the tenant",
)
async def remove_member(
    member_public_id: str,
    db: DBDep,
    ctx: TenantContext = Depends(get_tenant_context),
) -> ApiResponse[schemas.RemoveMemberResponse]:
    try:
        result = await service.remove_member(
            db, caller_tu=ctx.membership, current_user_id=ctx.membership.user_id,
            tenant=ctx.tenant, member_public_id=member_public_id,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error removing member")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not remove member. Please try again later.",
        )
    return ApiResponse(success=True, message="Member removed successfully.", data=result)


# =============================================================================
# ADMIN ENDPOINTS — SUPER ADMIN ONLY
# =============================================================================

@router.get(
    "/admin/",
    response_model=PagedApiResponse[schemas.AdminTenantListResponse],
    status_code=status.HTTP_200_OK,
    summary="[Admin] List all tenants across the platform",
)
async def admin_list_tenants(
    db: DBDep,
    _=Depends(require_superadmin),
    tenant_status: Optional[TenantStatus] = Query(None, alias="status", description="Filter by tenant status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> PagedApiResponse[schemas.AdminTenantListResponse]:
    try:
        result, meta = await service.admin_list_tenants(
            db, status=tenant_status, skip=skip, limit=limit
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error listing all tenants (admin)")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch tenants. Please try again later.",
        )
    return PagedApiResponse(success=True, message="Tenants fetched successfully.", data=result, meta=meta)


@router.get(
    "/admin/{tenant_public_id}",
    response_model=ApiResponse[schemas.AdminTenantDetail],
    status_code=status.HTTP_200_OK,
    summary="[Admin] Get full detail of a specific tenant",
)
async def admin_get_tenant_detail(
    tenant_public_id: str,
    db: DBDep,
    _=Depends(require_superadmin),
) -> ApiResponse[schemas.AdminTenantDetail]:
    try:
        result = await service.admin_get_tenant_detail(db, tenant_public_id=tenant_public_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error fetching tenant detail (admin)")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch tenant detail. Please try again later.",
        )
    return ApiResponse(success=True, message="Tenant detail fetched successfully.", data=result)


# ----- Tenant mutations -------------------------------------------------------

@router.patch(
    "/admin/{tenant_public_id}",
    response_model=ApiResponse[schemas.TenantResponse],
    status_code=status.HTTP_200_OK,
    summary="[Admin] Update a tenant's profile",
)
async def admin_update_tenant(
    tenant_public_id: str,
    payload: schemas.TenantUpdateRequest,
    db: DBDep,
    _=Depends(require_superadmin),
) -> ApiResponse[schemas.TenantResponse]:
    try:
        result = await service.admin_update_tenant(
            db, payload=payload, tenant_public_id=tenant_public_id
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error updating tenant (admin)")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update tenant. Please try again later.",
        )
    return ApiResponse(success=True, message="Tenant updated successfully.", data=result)


@router.patch(
    "/admin/{tenant_public_id}/status",
    response_model=ApiResponse[schemas.TenantResponse],
    status_code=status.HTTP_200_OK,
    summary="[Admin] Change a tenant's status (activate, suspend, cancel, etc.)",
)
async def admin_update_tenant_status(
    tenant_public_id: str,
    payload: schemas.TenantStatusUpdateRequest,
    db: DBDep,
    _=Depends(require_superadmin),
) -> ApiResponse[schemas.TenantResponse]:
    try:
        result = await service.update_tenant_status(
            db, payload=payload, tenant_public_id=tenant_public_id
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error updating tenant status (admin)")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update tenant status. Please try again later.",
        )
    return ApiResponse(success=True, message="Tenant status updated.", data=result)


@router.delete(
    "/admin/{tenant_public_id}",
    response_model=ApiResponse[None],
    status_code=status.HTTP_200_OK,
    summary="[Admin] Soft-delete a tenant (data retained, access blocked)",
)
async def admin_delete_tenant(
    tenant_public_id: str,
    db: DBDep,
    _=Depends(require_superadmin),
) -> ApiResponse[None]:
    try:
        await service.admin_delete_tenant(db, tenant_public_id=tenant_public_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error deleting tenant (admin)")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not delete tenant. Please try again later.",
        )
    return ApiResponse(success=True, message="Tenant deleted successfully.", data=None)


# ----- Member mutations (bypass tenant-context — super admin is never a member) -----

@router.patch(
    "/admin/{tenant_public_id}/members/{member_public_id}/role",
    response_model=ApiResponse[schemas.TenantMemberResponse],
    status_code=status.HTTP_200_OK,
    summary="[Admin] Change a member's role",
)
async def admin_update_member_role(
    tenant_public_id: str,
    member_public_id: str,
    payload: schemas.UpdateMemberRoleRequest,
    db: DBDep,
    _=Depends(require_superadmin),
) -> ApiResponse[schemas.TenantMemberResponse]:
    try:
        result = await service.admin_update_member_role(
            db, tenant_public_id=tenant_public_id,
            member_public_id=member_public_id, payload=payload,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error updating member role (admin)")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update member role. Please try again later.",
        )
    return ApiResponse(success=True, message="Member role updated.", data=result)


@router.patch(
    "/admin/{tenant_public_id}/members/{member_public_id}/status",
    response_model=ApiResponse[schemas.TenantMemberResponse],
    status_code=status.HTTP_200_OK,
    summary="[Admin] Suspend or reactivate a member",
)
async def admin_update_member_status(
    tenant_public_id: str,
    member_public_id: str,
    payload: schemas.UpdateMemberStatusRequest,
    db: DBDep,
    _=Depends(require_superadmin),
) -> ApiResponse[schemas.TenantMemberResponse]:
    try:
        result = await service.admin_update_member_status(
            db, tenant_public_id=tenant_public_id,
            member_public_id=member_public_id, payload=payload,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error updating member status (admin)")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update member status. Please try again later.",
        )
    return ApiResponse(success=True, message="Member status updated.", data=result)


@router.delete(
    "/admin/{tenant_public_id}/members/{member_public_id}",
    response_model=ApiResponse[schemas.RemoveMemberResponse],
    status_code=status.HTTP_200_OK,
    summary="[Admin] Remove a member from a tenant",
)
async def admin_remove_member(
    tenant_public_id: str,
    member_public_id: str,
    db: DBDep,
    _=Depends(require_superadmin),
) -> ApiResponse[schemas.RemoveMemberResponse]:
    try:
        result = await service.admin_remove_member(
            db, tenant_public_id=tenant_public_id,
            member_public_id=member_public_id,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error removing member (admin)")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not remove member. Please try again later.",
        )
    return ApiResponse(success=True, message="Member removed successfully.", data=result)