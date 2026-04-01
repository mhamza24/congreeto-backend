"""
router.py — FastAPI route definitions for the chat module.

Conventions
───────────
- Routes only handle HTTP concerns: request parsing, response shaping, HTTP
  status codes. No business logic lives here.
- Business logic exceptions (ValueError) map to 404; unexpected exceptions
  map to 500. A proper exception handler is registered on the app in main.py
  (see below), so individual try/except blocks are not needed per route.
- tenant_id is injected via dependency (auth token, header, etc.).
  Hardcoded "veloce" default is kept only while auth is not wired up.
- GET /all uses Query params (not a request body) — correct REST semantics.
"""

from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from passlib.exc import InvalidTokenError
import sentry_sdk
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse
from . import schemas,service
from app.modules.chat.models import ConversationStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

DBDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/signup",
    response_model=ApiResponse[schemas.SignupResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user account and send a welcome and OTP verification email",
)
async def signup_endpoint(
    payload: schemas.SignupRequest,
    db: DBDep,
) -> ApiResponse[schemas.SignupResponse]:
    try:
        reply = await service.create_user(
            db,
            payload=payload,
        )
    except HTTPException:
        raise                          
    except Exception:
        logger.exception("Unexpected error in user signup")
        sentry_sdk.capture_exception(Exception)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process your request. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="Signup successful. Please check your email for the OTP code.",
        data=reply,
    )

@router.post(
    "/login",
    response_model=ApiResponse[schemas.LoginResponse],
    status_code=status.HTTP_200_OK,
    summary="logged in a user",
)
async def login_endpoint(
    payload: schemas.LoginRequest,
    db: DBDep,
) -> ApiResponse[schemas.LoginResponse]:
    try:
        reply = await service.login_user(
            db,
            payload=payload,
        )
    except HTTPException:
        raise                          
    except Exception:
        logger.exception("Unexpected error in user login")
        sentry_sdk.capture_exception(Exception)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process your request. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="Login successful.",
        data=reply,
    )


@router.post(
    "/refresh",
    response_model=ApiResponse[schemas.RefreshResponse],
    status_code=status.HTTP_200_OK,
    summary="Get new access token using refresh token",
)
async def refresh_token_endpoint(
    payload: schemas.RefreshRequest,
    db: DBDep,
) -> ApiResponse[schemas.RefreshResponse]:
    try:
        reply = await service.refresh_access_token(db, refresh_token=payload.refresh_token)
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token. Please login again.",
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during token refresh")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return ApiResponse(
        success=True,
        message="Token refreshed.",
        data=reply,
    )