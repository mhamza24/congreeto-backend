from __future__ import annotations

from app.config.settings import get_settings
from fastapi import status
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import OTPPurpose, UserStatus
from app.core.exceptions import EmailAlreadyExistsError, InvalidCredentialsError, InvalidTokenError, http_exception_handler
from app.modules.models.otp import OTPVerification
from app.modules.onboarding.models import utcnow
from app.modules.open_ai import service as openai_service
from app.modules.auth import tasks as background_tasks
from app.utils.email_extractor import extract_and_validate_identity
from app.utils import hashing_utils
from app.utils.jwt_utils import create_access_token, create_refresh_token, decode_token, get_token_subject
from . import repository as repo, schemas, models
from app.modules.users import repository as user_repo, models as user_models

logger = logging.getLogger(__name__)

settings = get_settings()

# ---------------------------------------------------------------------------
# 1. User — create
# ---------------------------------------------------------------------------


async def create_user(
    db: AsyncSession,
    *,
    payload: schemas.SignupRequest,
) -> schemas.SignupResponse:

    # ── 1. Business rule ──────────────────────────────────────────────────
    existing = await user_repo.get_user_by_email(db, email=payload.email)
    if existing:
        raise EmailAlreadyExistsError(payload.email)

    # ── 2. Fields that need transformation before hitting the DB ──────────
    overrides = {
        "email": payload.email,
        "password_hash": hashing_utils.hash_password(payload.password),
    }

    # ── 3. Dynamic mapping — no manual field listing ever needed ──────────
    user = user_models.User.from_schema(payload, **overrides)

    # ── 4. Persist ────────────────────────────────────────────────────────
    user = await user_repo.create_user(db, user=user)

    # ── 5. Generate + persist OTP (same transaction) ──────────────────────
    raw_otp = hashing_utils.generate_otp()
    otp_record = OTPVerification(
        user_id=user.id,
        purpose=OTPPurpose.EMAIL_VERIFICATION,
        code_hash=hashing_utils.hash_otp(raw_otp),
        expires_at=utcnow() + timedelta(minutes=settings.OTP_EXPIRES_IN_MINUTES),
    )
    db.add(otp_record)
    await db.flush()

    # ── 6. Commit first, then enqueue ─────────────────────────────────────
    await db.commit()

    # ── 7. Enqueue — Celery dispatches to your worker ─────────────────────
    celery_task = background_tasks.send_otp_verification_email_task.delay(
       email=payload.email, first_name=payload.first_name, otp_code=raw_otp)

    logger.info(
        f"Task enqueued: {celery_task.id}, initial status: {celery_task.status}")

    return schemas.SignupResponse(
        public_id=user.public_id,
        message="Signup successful. Please check your email for the OTP code."
    )


async def login_user(
    db: AsyncSession,
    *,
    payload: schemas.LoginRequest,
) -> schemas.LoginResponse:

    existing_user = await user_repo.get_user_by_email(db, email=payload.email)

    if existing_user is None:
        raise InvalidCredentialsError()

    is_password_valid = hashing_utils.verify_password(
        payload.password, existing_user.password_hash
    )
    if not is_password_valid:
        raise InvalidCredentialsError()

    # ── Build whatever you need in the subject ────────────────────────────
    subject = get_token_subject(existing_user)

    return schemas.LoginResponse(
        tokens=schemas.TokenPair(
            access_token=create_access_token(subject),
            refresh_token=create_refresh_token(subject),
        ),

    )


async def refresh_access_token(
    db: AsyncSession,
    *,
    refresh_token: str,
) -> schemas.RefreshResponse:

    # 1. Decode and validate
    try:
        payload = decode_token(refresh_token)
        print(":::::::::::", payload)
    except Exception:
        raise InvalidTokenError("Invalid refresh token")

    # 2. Must be a refresh token, not access
    if payload.type != "refresh":
        raise InvalidTokenError("Token is not a refresh token")

    # 3. Check user still exists
    sub = payload.sub
    existing_user = await user_repo.get_user_by_id(db, user_id=sub["id"])
    if existing_user is None:
        raise InvalidTokenError("User no longer exists")

    # 4. Issue new access token only (refresh token stays the same)
    subject = get_token_subject(existing_user)

    return schemas.RefreshResponse(
        access_token=create_access_token(subject),
    )
