# app/modules/auth/otp_repository.py

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OTPPurpose
from app.modules.models.otp import OTPVerification
from app.utils.hashing_utils import generate_otp, hash_otp
from app.config.settings import get_settings
settings = get_settings()


# ── Write operations ─────────────────────────────────────────────────────────

async def create_otp(
    db: AsyncSession,
    *,
    user_id: int,
    purpose: OTPPurpose,
    expires_in_minutes: int = settings.OTP_EXPIRES_IN_MINUTES,
    ip_address: Optional[str] = None,
) -> str:
    """
    Issues a new OTP for the given user and purpose.
    Invalidates any previous unconsumed OTPs for the same (user, purpose).
    Returns the raw OTP code — send this to the user via email.
    """

    # 1. Invalidate previous unconsumed OTPs for same user + purpose
    await db.execute(
        update(OTPVerification)
        .where(
            and_(
                OTPVerification.user_id == user_id,
                OTPVerification.purpose == purpose,
                OTPVerification.consumed_at == None,
            )
        )
        .values(consumed_at=datetime.now(timezone.utc))  # mark as consumed
    )

    # 2. Generate new OTP
    raw_code = generate_otp()
    code_hash = hash_otp(raw_code)

    # 3. Persist hashed OTP
    otp = OTPVerification(
        user_id=user_id,
        purpose=purpose,
        code_hash=code_hash,
        expires_at=datetime.now(timezone.utc) +
        timedelta(minutes=expires_in_minutes),
        ip_address=ip_address,
    )
    db.add(otp)
    await db.commit()
    await db.refresh(otp)

    return raw_code   # ← only time raw code exists — pass to email service


async def verify_otp(
    db: AsyncSession,
    *,
    user_id: int,
    purpose: OTPPurpose,
    raw_code: str,
) -> bool:
    """
    Verifies submitted OTP code.
    - Increments attempts on every failure.
    - Marks consumed_at on success.
    - Returns True if valid, False otherwise.
    """

    # 1. Find latest unconsumed, non-expired, non-exhausted OTP
    result = await db.execute(
        select(OTPVerification)
        .where(
            and_(
                OTPVerification.user_id == user_id,
                OTPVerification.purpose == purpose,
                OTPVerification.consumed_at == None,
                OTPVerification.expires_at > datetime.now(timezone.utc),
                OTPVerification.attempts < OTPVerification.max_attempts,
            )
        )
        .order_by(OTPVerification.created_at.desc())
        .limit(1)
    )
    record = result.scalar_one_or_none()

    # 2. No valid record found
    if record is None:
        return False

    # 3. Hash mismatch — wrong code
    if record.code_hash != hash_otp(raw_code):
        record.attempts += 1    # increment attempts on failure
        await db.commit()
        return False

    # 4. Success — mark as consumed
    record.consumed_at = datetime.now(timezone.utc)
    await db.commit()
    return True


# ── Read operations ───────────────────────────────────────────────────────────

async def get_active_otp(
    db: AsyncSession,
    *,
    user_id: int,
    purpose: OTPPurpose,
) -> Optional[OTPVerification]:
    """
    Returns the latest unconsumed, non-expired OTP for a (user, purpose) pair.
    Useful for checking if a valid OTP already exists before issuing a new one.
    """
    result = await db.execute(
        select(OTPVerification)
        .where(
            and_(
                OTPVerification.user_id == user_id,
                OTPVerification.purpose == purpose,
                OTPVerification.consumed_at == None,
                OTPVerification.expires_at > datetime.now(timezone.utc),
                OTPVerification.attempts < OTPVerification.max_attempts,
            )
        )
        .order_by(OTPVerification.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_remaining_attempts(
    db: AsyncSession,
    *,
    user_id: int,
    purpose: OTPPurpose,
) -> int:
    """Returns how many attempts are left for the active OTP."""
    record = await get_active_otp(db, user_id=user_id, purpose=purpose)
    if record is None:
        return 0
    return record.max_attempts - record.attempts


# ── Cleanup ───────────────────────────────────────────────────────────────────

async def invalidate_all_otps(
    db: AsyncSession,
    *,
    user_id: int,
    purpose: OTPPurpose,
) -> None:
    """
    Force-invalidates all OTPs for a user+purpose.
    Call this after successful email verification or password reset.
    """
    await db.execute(
        update(OTPVerification)
        .where(
            and_(
                OTPVerification.user_id == user_id,
                OTPVerification.purpose == purpose,
                OTPVerification.consumed_at == None,
            )
        )
        .values(consumed_at=datetime.now(timezone.utc))
    )
    await db.commit()
