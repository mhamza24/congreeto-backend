# app/modules/tenants/api.py

from __future__ import annotations

import logging
from typing import Optional, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.dependencies.auth import get_current_user
from app.core.database import get_db
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
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.TenantResponse]:
    """
    Creates a new tenant and assigns the calling user as primary owner.
    Called during company onboarding after email verification.
    Tenant starts as 'pending_plan' — redirect to plan selection from frontend.
    """
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

    return ApiResponse(
        success=True,
        message="Tenant created successfully.",
        data=result,
    )


@router.get(
    "/{tenant_public_id}",
    response_model=ApiResponse[schemas.MyTenantContext],
    status_code=status.HTTP_200_OK,
    summary="Get your context within a tenant",
)
async def get_my_tenant(
    tenant_public_id: str,
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.MyTenantContext]:
    """
    Returns the calling user's role and tenant info.
    Used to populate the dashboard sidebar and permission gates.
    """
    try:
        result = await service.get_my_tenant(
            db, current_user=current_user, tenant_public_id=tenant_public_id
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
    tenant_public_id: str,
    payload: schemas.TenantUpdateRequest,
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.TenantResponse]:
    try:
        result = await service.update_tenant(
            db,
            payload=payload,
            current_user=current_user,
            tenant_public_id=tenant_public_id,
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
    # TODO: swap get_current_user → get_super_admin once that dep exists
) -> ApiResponse[schemas.TenantResponse]:
    """Super-admin only. Suspend, reactivate, or cancel a tenant."""
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
    tenant_public_id: str,
    db: DBDep,
    current_user=Depends(get_current_user),
    role: Optional[TenantRole] = Query(None, description="Filter by role"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> ApiResponse[schemas.MemberListResponse]:
    try:
        result = await service.list_members(
            db,
            current_user=current_user,
            tenant_public_id=tenant_public_id,
            role=role,
            skip=skip,
            limit=limit,
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
    tenant_public_id: str,
    payload: schemas.InviteUserRequest,
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.InviteResponse]:
    """
    Signs an invite token and sends an email.
    The invitee clicks the link and hits POST /tenants/invite/accept.
    """
    try:
        result = await service.invite_user(
            db,
            payload=payload,
            current_user=current_user,
            tenant_public_id=tenant_public_id,
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
    """
    Public endpoint — no auth required.
    Invitee submits the token from their email + their profile details.
    Creates their account (if new) and adds them to the tenant.
    """
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
    tenant_public_id: str,
    member_public_id: str,
    payload: schemas.UpdateMemberRoleRequest,
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.TenantMemberResponse]:
    try:
        result = await service.update_member_role(
            db,
            payload=payload,
            current_user=current_user,
            tenant_public_id=tenant_public_id,
            member_public_id=member_public_id,
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


@router.delete(
    "/{tenant_public_id}/members/{member_public_id}",
    response_model=ApiResponse[schemas.RemoveMemberResponse],
    status_code=status.HTTP_200_OK,
    summary="Remove a member from the tenant",
)
async def remove_member(
    tenant_public_id: str,
    member_public_id: str,
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.RemoveMemberResponse]:
    """
    Admin/owner can remove any non-owner member.
    Members can also remove themselves (leave the tenant).
    """
    try:
        result = await service.remove_member(
            db,
            current_user=current_user,
            tenant_public_id=tenant_public_id,
            member_public_id=member_public_id,
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