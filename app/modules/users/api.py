# app/modules/users/api.py

from __future__ import annotations

import logging
from typing import Optional, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.dependencies.auth import get_current_user
from app.core.database import get_db
from app.dependencies.user import get_verified_user
from app.modules.users import schemas, service
from app.core.enums import TenantRole
from app.modules.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["Users"])

DBDep = Annotated[AsyncSession, Depends(get_db)]

# =============================================================================
# USER ENDPOINTS
# =============================================================================


@router.get(
    "/me",
    response_model=ApiResponse[schemas.UserProfileResponse],  
    status_code=status.HTTP_200_OK,                           
    summary="Get current user profile.",
)
async def user_info(
    db: DBDep,
    current_user: User = Depends(get_current_user),        
) -> ApiResponse[schemas.UserProfileResponse]:
    """
    Get the profile of the currently authenticated user.
    """
    try:
        result = await service.get_current_user_profile(      
            db,
            current_user=current_user,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error getting current user profile")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not get current user profile. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="User profile fetched successfully.",
        data=result,
    )