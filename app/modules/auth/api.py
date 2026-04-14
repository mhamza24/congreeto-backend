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

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import sentry_sdk
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import InvalidOTPError
from app.core.response import ApiResponse
from app.dependencies.auth import get_current_user, require_superadmin
from . import schemas, service

_bearer = HTTPBearer(auto_error=False)

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
    request: Request,
    db: DBDep,
) -> ApiResponse[schemas.SignupResponse]:
    try:
        reply = await service.create_user(
            db,
            payload=payload,
            request=request,
        )
    except HTTPException:
        raise                          
    except Exception:
        logger.exception("Unexpected error in user signup")
        sentry_sdk.capture_exception()
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
    request: Request,
    db: DBDep,
) -> ApiResponse[schemas.LoginResponse]:
    try:
        reply = await service.login_user(
            db,
            payload=payload,
            request=request,
        )
    except HTTPException:
        raise                      
    except Exception:
        logger.exception("Unexpected error in user login")
        sentry_sdk.capture_exception()
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
    "/admin/signup",
    response_model=ApiResponse[schemas.AdminSignupResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new superadmin account (requires existing superadmin)",
)
async def admin_signup_endpoint(
    payload: schemas.AdminSignupRequest,
    db: DBDep,
    _: object = Depends(require_superadmin),
) -> ApiResponse[schemas.AdminSignupResponse]:
    try:
        reply = await service.create_admin_user(db, payload=payload)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error in admin signup")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process your request. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="Admin account created successfully.",
        data=reply,
    )


@router.post(
    "/admin/login",
    response_model=ApiResponse[schemas.LoginResponse],
    status_code=status.HTTP_200_OK,
    summary="Admin portal login — validates credentials and superadmin role",
)
async def admin_login_endpoint(
    payload: schemas.LoginRequest,
    db: DBDep,
) -> ApiResponse[schemas.LoginResponse]:
    try:
        reply = await service.login_admin_user(db, payload=payload)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error in admin login")
        sentry_sdk.capture_exception()
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
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during token refresh")
        sentry_sdk.capture_exception()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return ApiResponse(
        success=True,
        message="Token refreshed.",
        data=reply,
    )


@router.post(
    "/verify-email",
    response_model=ApiResponse[schemas.OTPVerifyResponse],
    status_code=status.HTTP_200_OK,
    summary="Verify email with OTP",
)
async def verify_email_endpoint(
    payload: schemas.OTPVerifyRequest,
    db: DBDep,
) -> ApiResponse[schemas.OTPVerifyResponse]:
    try:
        reply = await service.verify_email(db, payload=payload)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during email verification")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process your request. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="Email verified successfully.",
        data=reply,
    )


@router.get(
    "/resend-otp/status",
    response_model=ApiResponse[schemas.ResendOTPStatusResponse],
    status_code=status.HTTP_200_OK,
    summary="Check if resend OTP button should be shown",
)
async def resend_otp_status_endpoint(
    current_user=Depends(get_current_user),
) -> ApiResponse[schemas.ResendOTPStatusResponse]:
    try:
        result = await service.get_resend_otp_status(current_user=current_user)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error checking OTP resend status")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process your request. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="OTP resend status retrieved.",
        data=result,
    )


@router.get(
    "/resend-otp",
    response_model=ApiResponse[str],
    status_code=status.HTTP_200_OK,
    summary="Resend OTP to email",
)
async def resend_otp_endpoint(
    # payload: None,  # No body needed since we get user from token; kept for schema consistency
    db: DBDep,
    current_user=Depends(get_current_user),
) -> ApiResponse[str]:
    try:
        await service.resend_otp(db, current_user=current_user)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during OTP resend")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process your request. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="OTP sent. Please check your email.",
        data=None,
    )


@router.post(
    "/verify-login-otp",
    response_model=ApiResponse[schemas.LoginResponse],
    status_code=status.HTTP_200_OK,
    summary="Step 2 of 2FA login — verify OTP and receive tokens",
)
async def verify_login_otp_endpoint(
    payload: schemas.VerifyLoginOTPRequest,
    request: Request,
    db: DBDep,
) -> ApiResponse[schemas.LoginResponse]:
    try:
        reply = await service.verify_login_otp(db, payload=payload, request=request)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during login OTP verification")
        sentry_sdk.capture_exception()
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
    "/logout",
    response_model=ApiResponse[None],
    status_code=status.HTTP_200_OK,
    summary="Invalidate access (and optionally refresh) token",
)
async def logout_endpoint(
    payload: schemas.LogoutRequest,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> ApiResponse[None]:
    access_token = credentials.credentials if credentials else None
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token.")
    try:
        await service.logout_user(
            access_token=access_token,
            refresh_token=payload.refresh_token,
        )
    except Exception:
        logger.exception("Unexpected error during logout")
        sentry_sdk.capture_exception()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return ApiResponse(success=True, message="Logged out successfully.", data=None)


@router.post(
    "/forgot-password",
    response_model=ApiResponse[None],
    status_code=status.HTTP_200_OK,
    summary="Send a password-reset OTP to the given email",
)
async def forgot_password_endpoint(
    payload: schemas.ForgotPasswordRequest,
    db: DBDep,
) -> ApiResponse[None]:
    try:
        await service.forgot_password(db, payload=payload)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during forgot password")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process your request. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="Reset code sent. Please check your email.",
        data=None,
    )


@router.post(
    "/verify-forgot-password",
    response_model=ApiResponse[None],
    status_code=status.HTTP_200_OK,
    summary="Verify reset OTP and set a new password",
)
async def verify_forgot_password_endpoint(
    payload: schemas.VerifyForgotPasswordRequest,
    db: DBDep,
) -> ApiResponse[None]:
    try:
        await service.verify_forgot_password(db, payload=payload)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during password reset verification")
        sentry_sdk.capture_exception()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process your request. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="Password updated successfully. You can now log in.",
        data=None,
    )

