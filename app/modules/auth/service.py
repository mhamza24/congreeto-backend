from __future__ import annotations

from app.config.settings import get_settings
from fastapi import status
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import OTPPurpose, UserStatus
from app.core.exceptions import EmailAlreadyExistsError, EmailAlreadyVerifiedError, InvalidCredentialsError, InvalidOTPError, InvalidTokenError, InvalidTokenTypeError, UserNotExistError, http_exception_handler
from app.modules.models.otp import OTPVerification
from app.modules.open_ai import service as openai_service
from app.modules.auth import tasks as background_tasks
from app.utils.email_extractor import extract_and_validate_identity
from app.utils import hashing_utils
from app.utils.jwt_utils import create_access_token, create_refresh_token, decode_token, get_token_subject
from app.utils.rate_limit import check_otp_rate_limit, record_otp_request
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
        expires_at=datetime.utcnow() + timedelta(minutes=settings.OTP_EXPIRES_IN_MINUTES),
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

    # Update last login time
    await user_repo.update_login_time_by_id(db, user_id=existing_user.id)
    
    # ── Build whatever you need in the subject ────────────────────────────
    jwt_subject = get_token_subject(existing_user)

    return schemas.LoginResponse(
        tokens=schemas.TokenPair(
            access_token=create_access_token(jwt_subject),
            refresh_token=create_refresh_token(jwt_subject),
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
    except Exception:
        raise InvalidTokenError("Invalid refresh token")

    # 2. Must be a refresh token, not access
    if payload.type != "refresh":
        raise InvalidTokenTypeError()

    # 3. Check user still exists
    sub = payload.sub
    existing_user = await user_repo.get_user_by_id(db, id=sub["id"])
    if existing_user is None:
        raise UserNotExistError()

    # 4. Issue new access token only (refresh token stays the same)
    subject = get_token_subject(existing_user)

    return schemas.RefreshResponse(
        access_token=create_access_token(subject),
    )


async def verify_email(
    db: AsyncSession,
    *,
    payload: schemas.OTPVerifyRequest,
    current_user: user_models.User,
) -> schemas.OTPVerifyResponse:
    """
    Verifies the email OTP for the current user.

    DB hits: 2
      1. get_active_otp  — fetch OTP record
      2. mark_email_verified — update user (returns updated user, no re-fetch)

    No re-fetch of OTP record after verify_otp — attempts computed in-memory
    from the already-loaded SQLAlchemy object.
    """

    # 1. Guard — already verified
    if current_user.email_verified_at is not None:
        raise EmailAlreadyVerifiedError()

    # 2. DB hit 1 — fetch OTP record once, reuse throughout
    otp_record = await repo.get_active_otp(
        db,
        user_id=current_user.id,
        purpose=OTPPurpose.EMAIL_VERIFICATION,
    )
    if otp_record is None:
        raise InvalidOTPError()  # generic — don't leak expired/consumed/never-issued

    # 3. Verify — constant-time compare inside, increments attempts on failure
    #    No DB re-fetch — record already in memory
    is_valid = await repo.verify_otp(
        db,
        record=otp_record,
        raw_code=payload.otp,
    )
    if not is_valid:
        # remaining_attempts uses already-incremented in-memory value — no DB call
        remaining = repo.remaining_attempts(otp_record)
        raise InvalidOTPError(f"Invalid OTP. {remaining} attempt(s) remaining.")

    # 4. DB hit 2 — mark verified, get updated user back (no extra fetch)
    updated_user = await user_repo.mark_email_verified_and_update_status(db, user_id=current_user.id)

    # 5. Issue fresh token pair with verified identity
    token_subject = get_token_subject(updated_user)
    return schemas.OTPVerifyResponse(
        message="Email verified successfully.",
        tokens=schemas.TokenPair(
            access_token=create_access_token(token_subject),
            refresh_token=create_refresh_token(token_subject),
        ),
    )


async def get_resend_otp_status(
    *,
    current_user: user_models.User,
) -> schemas.ResendOTPStatusResponse:
    """
    Returns whether the resend button should be shown.
    If not, includes remaining wait time in seconds, minutes, and hours.
    """
    from app.utils.rate_limit import _otp_lockout_key, _otp_cooldown_key
    from app.core.redis import redis_client

    # Check hard lockout first
    locked = await redis_client.get(_otp_lockout_key(current_user.id))
    if locked:
        ttl = await redis_client.ttl(_otp_lockout_key(current_user.id))
        ttl = max(ttl, 0)
        return schemas.ResendOTPStatusResponse(
            can_resend=False,
            remaining_seconds=ttl,
            remaining_minutes=round(ttl / 60, 2),
            remaining_hours=round(ttl / 3600, 2),
        )

    # Check cooldown
    cooldown = await redis_client.get(_otp_cooldown_key(current_user.id))
    if cooldown:
        ttl = await redis_client.ttl(_otp_cooldown_key(current_user.id))
        ttl = max(ttl, 0)
        return schemas.ResendOTPStatusResponse(
            can_resend=False,
            remaining_seconds=ttl,
            remaining_minutes=round(ttl / 60, 2),
            remaining_hours=round(ttl / 3600, 2),
        )

    return schemas.ResendOTPStatusResponse(can_resend=True)


async def resend_otp(
    db: AsyncSession,
    *,
    current_user: user_models.User,
) -> str:

    # 1. Already verified — nothing to do
    if current_user.email_verified_at is not None:
        return "Email already verified."

    # 2. Check rate limit — raises RateLimitError if abusing
    await check_otp_rate_limit(current_user.id)

    # 3. Record this request + set cooldown
    attempt = await record_otp_request(current_user.id)
    logger.info(f"OTP resend attempt {attempt} for user {current_user.public_id}")

    # 4. Issue new OTP — auto-invalidates old ones in DB
    raw_code = await repo.create_otp(
        db,
        user_id=current_user.id,
        purpose=OTPPurpose.EMAIL_VERIFICATION,
        expires_in_minutes=settings.OTP_EXPIRES_IN_MINUTES,
    )

    # 5. Send email via celery
    celery_task = background_tasks.send_otp_verification_email_task.delay(
        email=current_user.email,
        first_name=current_user.first_name,
        otp_code=raw_code,                   # ← send raw_code not a new hash
    )
    logger.info(f"OTP email enqueued: task={celery_task.id} attempt={attempt}")

    return "OTP resent successfully."

