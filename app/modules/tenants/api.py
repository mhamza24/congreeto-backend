from __future__ import annotations

import logging
from typing import Optional, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import TenantContext, get_tenant_context, require_write
from app.core.database import get_db
from app.dependencies.user import get_verified_user
from app.modules.tenants import schemas, service
from app.core.enums import TenantRole

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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch tenants. Please try again later.",
        )
    return ApiResponse(success=True, message="Tenants fetched successfully.", data=result)


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
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.TenantResponse]:
    try:
        result = await service.update_tenant_status(
            db, payload=payload, tenant_public_id=tenant_public_id
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error updating tenant status")
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not remove member. Please try again later.",
        )
    return ApiResponse(success=True, message="Member removed successfully.", data=result)