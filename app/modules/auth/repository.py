# app/modules/auth/otp_repository.py

import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OTPPurpose
from app.modules.models.otp import OTPVerification
from app.utils.hashing_utils import generate_otp, hash_otp
from app.config.settings import get_settings

settings = get_settings()


# ── Write operations ──────────────────────────────────────────────────────────

async def create_otp(
    db: AsyncSession,
    *,
    user_id: int,
    purpose: OTPPurpose,
    expires_in_minutes: int = settings.OTP_EXPIRES_IN_MINUTES,
    ip_address: Optional[str] = None,
) -> str:
    logger.debug("[auth] create_otp user_id=%d purpose=%s", user_id, purpose)
    """
    Issues a new OTP for the given user and purpose.
    Invalidates any previous unconsumed OTPs for the same (user, purpose).
    Uses SELECT FOR UPDATE to prevent race conditions on concurrent requests.
    Returns the raw OTP code — send this to the user via email/SMS.
    """
    # 1. Lock existing unconsumed OTPs to prevent race condition
    await db.execute(
        select(OTPVerification)
        .where(
            and_(
                OTPVerification.user_id == user_id,
                OTPVerification.purpose == purpose,
                OTPVerification.consumed_at.is_(None),
            )
        )
        .with_for_update()  # row-level lock — prevents double issuance
    )

    # 2. Invalidate all previous unconsumed OTPs
    await db.execute(
        update(OTPVerification)
        .where(
            and_(
                OTPVerification.user_id == user_id,
                OTPVerification.purpose == purpose,
                OTPVerification.consumed_at.is_(None),
            )
        )
        .values(consumed_at=datetime.now(timezone.utc))
    )

    # 3. Generate and persist new hashed OTP
    raw_code = generate_otp()
    otp = OTPVerification(
        user_id=user_id,
        purpose=purpose,
        code_hash=hash_otp(raw_code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
        ip_address=ip_address,
    )
    db.add(otp)
    await db.commit()
    await db.refresh(otp)

    logger.info("[auth] create_otp issued user_id=%d purpose=%s expires_in=%dm", user_id, purpose, expires_in_minutes)
    return raw_code  # ← only moment raw code exists — caller passes to email service


async def verify_otp(
    db: AsyncSession,
    *,
    record: OTPVerification,  # already-fetched record — no re-query needed
    raw_code: str,
) -> bool:
    """
    Verifies submitted OTP against the fetched record.
    - Uses constant-time comparison to prevent timing attacks.
    - Increments attempts on failure.
    - Marks consumed_at on success.
    """
    expected = hash_otp(raw_code)

    # Constant-time comparison — prevents timing attacks
    if not hmac.compare_digest(record.code_hash, expected):
        record.attempts += 1
        await db.commit()
        logger.warning("[auth] verify_otp failed invalid code user_id=%d purpose=%s attempts=%d", record.user_id, record.purpose, record.attempts)
        return False

    record.consumed_at = datetime.now(timezone.utc)
    record.code_hash=None # clear hash on success — prevents reuse even if DB is compromised
    await db.commit()
    logger.info("[auth] verify_otp success user_id=%d purpose=%s", record.user_id, record.purpose)
    return True


# ── Read operations ───────────────────────────────────────────────────────────

async def get_active_otp_by_hash(
    db: AsyncSession,
    *,
    code_hash: str,
    purpose: OTPPurpose,
) -> Optional[OTPVerification]:
    """
    Looks up an active OTP by its stored hash and purpose.
    Used by accept_invite to resolve user_id without a Redis lookup.
    """
    result = await db.execute(
        select(OTPVerification)
        .where(
            and_(
                OTPVerification.code_hash == code_hash,
                OTPVerification.purpose == purpose,
                OTPVerification.consumed_at.is_(None),
                OTPVerification.expires_at > datetime.now(timezone.utc),
                OTPVerification.attempts < OTPVerification.max_attempts,
            )
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_active_otp(
    db: AsyncSession,
    *,
    user_id: int,
    purpose: OTPPurpose,
) -> Optional[OTPVerification]:
    """
    Returns the latest unconsumed, non-expired, non-locked-out OTP
    for a (user, purpose) pair.
    """
    result = await db.execute(
        select(OTPVerification)
        .where(
            and_(
                OTPVerification.user_id == user_id,
                OTPVerification.purpose == purpose,
                OTPVerification.consumed_at.is_(None),
                OTPVerification.expires_at > datetime.now(timezone.utc),
                OTPVerification.attempts < OTPVerification.max_attempts,
            )
        )
        .order_by(OTPVerification.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def remaining_attempts(record: OTPVerification) -> int:
    """
    Pure in-memory computation — no DB call.
    Call after verify_otp so record.attempts is already incremented.
    """
    return max(0, record.max_attempts - record.attempts)


# ── Cleanup ───────────────────────────────────────────────────────────────────

async def invalidate_all_otps(
    db: AsyncSession,
    *,
    user_id: int,
    purpose: OTPPurpose,
) -> None:
    """
    Force-invalidates all active OTPs for a user+purpose.
    Call this after successful verification or password reset.
    """
    await db.execute(
        update(OTPVerification)
        .where(
            and_(
                OTPVerification.user_id == user_id,
                OTPVerification.purpose == purpose,
                OTPVerification.consumed_at.is_(None),
            )
        )
        .values(consumed_at=datetime.now(timezone.utc))
    )
    await db.commit()