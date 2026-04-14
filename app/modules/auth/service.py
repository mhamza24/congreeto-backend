from __future__ import annotations

from app.config.settings import get_settings
from fastapi import Request, status
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import OTPPurpose, UserStatus
from app.core.exceptions import EmailAlreadyExistsError, EmailAlreadyVerifiedError, InvalidCredentialsError, InvalidOTPError, InvalidTokenError, InvalidTokenTypeError, UserNotExistError, http_exception_handler
from app.modules.models.otp import OTPVerification
from app.modules.open_ai import service as openai_service
from app.modules.auth import tasks as background_tasks
from app.modules.audit import repository as audit
from app.utils.email_extractor import extract_and_validate_identity
from app.utils import hashing_utils
from app.utils.jwt_utils import create_access_token, create_refresh_token, decode_token, get_token_subject, blacklist_token
from app.utils.rate_limit import (
    check_otp_rate_limit,
    record_otp_request,
    check_login_otp_lockout,
    set_login_otp_lockout,
    check_login_failure_lockout,
    record_login_failure,
    clear_login_failures,
)
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
    request: Optional[Request] = None,
) -> schemas.SignupResponse:

    logger.info("[auth] signup attempt email=%s", payload.email)
    # ── 1. Business rule ──────────────────────────────────────────────────
    existing = await user_repo.get_user_by_email(db, email=payload.email)
    if existing:
        logger.warning("[auth] signup conflict email already exists email=%s", payload.email)
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
        expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=settings.OTP_EXPIRES_IN_MINUTES),
    )
    db.add(otp_record)
    await db.flush()

    # ── 5b. Audit log — user signup ────────────────────────────────────────
    await audit.write(
        db,
        entity_type="users",
        action=audit.CREATE,
        user_id=user.id,
        entity_id=user.id,
        diff={"after": {"email": user.email, "public_id": user.public_id}},
        request=request,
    )

    # ── 6. Commit first, then enqueue ─────────────────────────────────────
    await db.commit()

    # ── 7. Enqueue — Celery dispatches to your worker ─────────────────────
    celery_task = background_tasks.send_otp_verification_email_task.delay(
       email=payload.email, first_name=payload.first_name, otp_code=raw_otp)

    logger.info("[auth] user created public_id=%s email=%s task=%s", user.public_id, payload.email, celery_task.id)

    return schemas.SignupResponse(
        public_id=user.public_id,
        message="Signup successful. Please check your email for the OTP code."
    )


async def login_user(
    db: AsyncSession,
    *,
    payload: schemas.LoginRequest,
    request: Optional[Request] = None,
) -> schemas.LoginResponse:

    logger.info("[auth] login attempt email=%s", payload.email)
    existing_user = await user_repo.get_user_by_email(db, email=payload.email)

    if existing_user is None:
        logger.warning("[auth] login failed user not found email=%s", payload.email)
        raise InvalidCredentialsError()

    # Check per-account lockout before verifying the password (prevents timing oracle)
    await check_login_failure_lockout(existing_user.id)

    is_password_valid = hashing_utils.verify_password(
        payload.password, existing_user.password_hash
    )
    if not is_password_valid:
        await record_login_failure(existing_user.id)
        logger.warning("[auth] login failed invalid password email=%s", payload.email)
        raise InvalidCredentialsError()

    # Successful auth — clear failure counter
    await clear_login_failures(existing_user.id)

    # ── Email verification gate — block login OTP until email is confirmed ──
    if existing_user.email_verified_at is None:
        logger.info(
            "[auth] login blocked email not verified public_id=%s", existing_user.public_id
        )
        return schemas.LoginResponse(
            message="Please verify your email before logging in.",
            requires_email_verification=True,
        )

    # ── 2FA — if enabled, send login OTP and defer token issuance ─────────
    if existing_user.two_fa_enabled:
        raw_otp = await repo.create_otp(
            db,
            user_id=existing_user.id,
            purpose=OTPPurpose.LOGIN_OTP,
            expires_in_minutes=settings.OTP_EXPIRES_IN_MINUTES,
        )
        background_tasks.send_login_otp_email_task.delay(
            email=existing_user.email,
            first_name=existing_user.first_name,
            otp_code=raw_otp,
        )
        logger.info("[auth] 2FA OTP sent public_id=%s email=%s", existing_user.public_id, existing_user.email)
        return schemas.LoginResponse(
            message="OTP sent to your email. Please verify to continue.",
            requires_2fa=True,
        )

    # ── No 2FA — issue tokens immediately ────────────────────────────────
    await user_repo.update_login_time_by_id(db, user_id=existing_user.id)
    logger.info("[auth] login success public_id=%s email=%s", existing_user.public_id, existing_user.email)

    # ── Audit log — successful login ──────────────────────────────────────
    await audit.write(
        db,
        entity_type="users",
        action=audit.LOGIN,
        user_id=existing_user.id,
        entity_id=existing_user.id,
        diff={},
        request=request,
    )
    await db.commit()

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
    except (ValueError, KeyError) as exc:
        logger.warning("[auth] refresh_token decode failed reason=%s", type(exc).__name__)
        raise InvalidTokenError("Invalid refresh token") from exc
    except Exception as exc:
        logger.warning("[auth] refresh_token unexpected decode error type=%s", type(exc).__name__)
        raise InvalidTokenError("Invalid refresh token") from exc

    # 2. Must be a refresh token, not access
    if payload.type != "refresh":
        logger.warning("[auth] refresh_token wrong type type=%s", payload.type)
        raise InvalidTokenTypeError()

    # 3. Check user still exists
    sub = payload.sub
    existing_user = await user_repo.get_user_by_id(db, id=sub["id"])
    if existing_user is None:
        logger.warning("[auth] refresh_token user not found id=%s", sub.get("id"))
        raise UserNotExistError()

    # 4. Issue new access token only (refresh token stays the same)
    logger.debug("[auth] access token refreshed user=%s", existing_user.public_id)
    subject = get_token_subject(existing_user)

    return schemas.RefreshResponse(
        access_token=create_access_token(subject),
    )


async def verify_email(
    db: AsyncSession,
    *,
    payload: schemas.OTPVerifyRequest,
) -> schemas.OTPVerifyResponse:
    """
    Verifies the email OTP by email + OTP only — no token required.

    DB hits: 3
      1. get_user_by_email — resolve user from email
      2. get_active_otp    — fetch OTP record
      3. mark_email_verified — update user (returns updated user, no re-fetch)
    """

    existing_user = await user_repo.get_user_by_email(db, email=payload.email)
    if existing_user is None:
        raise InvalidCredentialsError()

    logger.info("[auth] verify_email attempt user=%s", existing_user.public_id)
    # 1. Guard — already verified
    if existing_user.email_verified_at is not None:
        logger.warning("[auth] verify_email already verified user=%s", existing_user.public_id)
        raise EmailAlreadyVerifiedError()

    # 2. DB hit 2 — fetch OTP record once, reuse throughout
    otp_record = await repo.get_active_otp(
        db,
        user_id=existing_user.id,
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

    # 4. DB hit 3 — mark verified, get updated user back (no extra fetch)
    logger.info("[auth] email verified user=%s", existing_user.public_id)
    updated_user = await user_repo.mark_email_verified_and_update_status(db, user_id=existing_user.id)

    # 5. Issue fresh token pair with verified identity
    token_subject = get_token_subject(updated_user)
    return schemas.OTPVerifyResponse(
        message="Email verified successfully.",
        tokens=schemas.TokenPair(
            access_token=create_access_token(token_subject),
            refresh_token=create_refresh_token(token_subject),
        ),
    )


async def create_admin_user(
    db: AsyncSession,
    *,
    payload: schemas.AdminSignupRequest,
) -> schemas.AdminSignupResponse:

    logger.info("[auth] admin signup attempt email=%s", payload.email)
    # 1. Reject duplicate emails
    existing = await user_repo.get_user_by_email(db, email=payload.email)
    if existing:
        logger.warning("[auth] admin signup conflict email exists email=%s", payload.email)
        raise EmailAlreadyExistsError(payload.email)

    # 2. Build the user — mark as superadmin, active, and already verified
    overrides = {
        "email": payload.email.lower(),
        "password_hash": hashing_utils.hash_password(payload.password),
        "is_superadmin": True,
        "status": UserStatus.ACTIVE,
        "email_verified_at": datetime.now(timezone.utc),
    }

    user = user_models.User.from_schema(payload, **overrides)

    # 3. Persist — no OTP, no email
    user = await user_repo.create_user(db, user=user)
    await db.commit()
    logger.info("[auth] admin user created public_id=%s email=%s", user.public_id, user.email)

    return schemas.AdminSignupResponse(
        public_id=user.public_id,
    )


async def login_admin_user(
    db: AsyncSession,
    *,
    payload: schemas.LoginRequest,
) -> schemas.LoginResponse:

    logger.info("[auth] admin login attempt email=%s", payload.email)
    existing_user = await user_repo.get_user_by_email(db, email=payload.email)

    # Check 1: user exists
    if existing_user is None:
        logger.warning("[auth] admin login failed user not found email=%s", payload.email)
        raise InvalidCredentialsError()

    # Check 2: password valid — do this before the superadmin check to keep
    # timing consistent and avoid leaking whether the account exists
    is_password_valid = hashing_utils.verify_password(
        payload.password, existing_user.password_hash
    )
    if not is_password_valid:
        logger.warning("[auth] admin login failed invalid password email=%s", payload.email)
        raise InvalidCredentialsError()

    # Check 3: must be a superadmin — same generic error to prevent enumeration
    if not existing_user.is_superadmin:
        logger.warning("[auth] admin login rejected not superadmin email=%s", payload.email)
        raise InvalidCredentialsError()

    # Check 4: account must not be suspended or inactive
    if existing_user.status in (UserStatus.SUSPENDED, UserStatus.INACTIVE):
        logger.warning("[auth] admin login rejected account status=%s email=%s", existing_user.status, payload.email)
        raise InvalidCredentialsError()

    await user_repo.update_login_time_by_id(db, user_id=existing_user.id)
    logger.info("[auth] admin login success public_id=%s email=%s", existing_user.public_id, existing_user.email)

    jwt_subject = get_token_subject(existing_user)

    return schemas.LoginResponse(
        tokens=schemas.TokenPair(
            access_token=create_access_token(jwt_subject),
            refresh_token=create_refresh_token(jwt_subject),
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


async def verify_login_otp(
    db: AsyncSession,
    *,
    payload: schemas.VerifyLoginOTPRequest,
    request: Optional[Request] = None,
) -> schemas.LoginResponse:
    """
    Step 2 of the 2FA login flow.
    Verifies the LOGIN_OTP and issues tokens on success.
    Locks the user out for 24 h after 5 consecutive failures.
    """
    logger.info("[auth] verify_login_otp attempt email=%s", payload.email)

    # 1. Resolve user
    existing_user = await user_repo.get_user_by_email(db, email=payload.email)
    if existing_user is None:
        raise InvalidCredentialsError()

    # 2. Check Redis lockout before touching the DB OTP record
    await check_login_otp_lockout(existing_user.id)

    # 3. Fetch active OTP
    otp_record = await repo.get_active_otp(
        db,
        user_id=existing_user.id,
        purpose=OTPPurpose.LOGIN_OTP,
    )
    if otp_record is None:
        raise InvalidOTPError()

    # 4. Verify — increments attempts on failure
    is_valid = await repo.verify_otp(db, record=otp_record, raw_code=payload.otp)
    if not is_valid:
        remaining = repo.remaining_attempts(otp_record)
        if remaining == 0:
            await set_login_otp_lockout(existing_user.id)
            logger.warning(
                "[auth] verify_login_otp lockout triggered user=%s", existing_user.public_id
            )
            from app.core.exceptions import RateLimitError
            raise RateLimitError(
                "Too many failed attempts. Your account is locked for 24 hours."
            )
        raise InvalidOTPError(f"Invalid OTP. {remaining} attempt(s) remaining.")

    # 5. OTP valid — if email unverified, mark it verified now (email access proven via OTP)
    if existing_user.email_verified_at is None:
        existing_user = await user_repo.mark_email_verified_and_update_status(db, user_id=existing_user.id)
        logger.info("[auth] email auto-verified via 2FA login public_id=%s", existing_user.public_id)

    # 6. Update login time, audit, issue tokens
    await user_repo.update_login_time_by_id(db, user_id=existing_user.id)
    await audit.write(
        db,
        entity_type="users",
        action=audit.LOGIN,
        user_id=existing_user.id,
        entity_id=existing_user.id,
        diff={},
        request=request,
    )
    await db.commit()

    logger.info("[auth] verify_login_otp success public_id=%s", existing_user.public_id)
    jwt_subject = get_token_subject(existing_user)
    return schemas.LoginResponse(
        message="Login successful.",
        tokens=schemas.TokenPair(
            access_token=create_access_token(jwt_subject),
            refresh_token=create_refresh_token(jwt_subject),
        ),
    )


async def forgot_password(
    db: AsyncSession,
    *,
    payload: schemas.ForgotPasswordRequest,
) -> None:
    """
    Sends a password-reset OTP to the user's email.
    Always returns without error to prevent user enumeration — the caller
    receives the same response regardless of whether the email is registered.
    The OTP is sent via email only; it is never embedded in a URL.
    """
    logger.info("[auth] forgot_password request email=%s", payload.email)

    existing_user = await user_repo.get_user_by_email(db, email=payload.email)
    if existing_user is None:
        # Return silently — do not reveal whether the email is registered
        logger.info("[auth] forgot_password email not found (silent) email=%s", payload.email)
        return

    raw_otp = await repo.create_otp(
        db,
        user_id=existing_user.id,
        purpose=OTPPurpose.PASSWORD_RESET,
        expires_in_minutes=settings.OTP_EXPIRES_IN_MINUTES,
    )

    # Reset link contains only the email — OTP is delivered exclusively by email
    reset_link = f"{settings.FRONTEND_URL}/reset-password?email={existing_user.email}"

    background_tasks.send_forgot_password_email_task.delay(
        email=existing_user.email,
        first_name=existing_user.first_name,
        otp_code=raw_otp,
        reset_link=reset_link,
    )
    logger.info("[auth] forgot_password OTP sent public_id=%s", existing_user.public_id)


async def logout_user(
    *,
    access_token: str,
    refresh_token: Optional[str] = None,
) -> None:
    """
    Blacklists the provided tokens so they cannot be reused even before expiry.
    Both access and (optionally) refresh tokens are revoked.
    """
    await blacklist_token(access_token)
    if refresh_token:
        await blacklist_token(refresh_token)
    logger.info("[auth] tokens blacklisted (logout)")


async def verify_forgot_password(
    db: AsyncSession,
    *,
    payload: schemas.VerifyForgotPasswordRequest,
) -> None:
    """
    Verifies the password-reset OTP and updates the user's password.
    """
    logger.info("[auth] verify_forgot_password attempt email=%s", payload.email)

    existing_user = await user_repo.get_user_by_email(db, email=payload.email)
    if existing_user is None:
        raise InvalidCredentialsError()

    otp_record = await repo.get_active_otp(
        db,
        user_id=existing_user.id,
        purpose=OTPPurpose.PASSWORD_RESET,
    )
    if otp_record is None:
        raise InvalidOTPError()

    is_valid = await repo.verify_otp(db, record=otp_record, raw_code=payload.otp)
    if not is_valid:
        remaining = repo.remaining_attempts(otp_record)
        raise InvalidOTPError(f"Invalid OTP. {remaining} attempt(s) remaining.")

    # OTP valid — update password
    new_hash = hashing_utils.hash_password(payload.new_password)
    await user_repo.update_password_by_id(db, user_id=existing_user.id, new_password_hash=new_hash)

    logger.info("[auth] verify_forgot_password password updated public_id=%s", existing_user.public_id)

