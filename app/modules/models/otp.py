# models/otp.py
"""
OTPVerification — one row per issued OTP code.

WHY A SEPARATE TABLE (not a column on users):
- A user can have multiple OTPs in flight simultaneously:
  one for email verification AND one for password reset.
- Each has its own expiry, purpose, and consumed state.
- Appending a new OTP never touches the users row — no write contention.
- Expired/consumed OTPs are cheap to purge (DELETE WHERE expires_at < NOW()).

SECURITY DESIGN:
- code_hash: store SHA-256(otp_code), NEVER the raw 6-digit code.
  The raw code lives only in the email; only the hash hits the DB.
  This way a DB dump doesn't give an attacker valid OTP codes.
- max_attempts: reject after 5 wrong guesses to prevent brute-force on
  the 6-digit space (10^6 combinations).
- expires_at: short TTL — 10 min for signup/reset, 5 min for login OTP.
- consumed_at: set atomically when the code is successfully verified.
  CHECK: WHERE consumed_at IS NULL AND attempts < max_attempts AND expires_at > NOW()

CLEANUP:
  Run a nightly job:
      DELETE FROM otp_verifications WHERE expires_at < NOW() - INTERVAL '24h';
  Or use pg_partman if volume is high.

INDEXES:
  ix_otp_user_purpose_active — the primary lookup: find the latest valid OTP
      for a (user, purpose) pair. Partial: only non-consumed rows.
  ix_otp_expires — cleanup job scans by expires_at.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_base import Base, PublicIdMixin
from app.core.enums import OTPPurpose, otp_purpose_enum
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.modules.users.models import User

class OTPVerification(Base, PublicIdMixin):
    """
    Stores hashed OTP codes for email verification and password reset.

    Service layer usage example:

        # Issue
        otp = OTPVerification(
            user_id   = user.id,
            purpose   = OTPPurpose.EMAIL_VERIFICATION,
            code_hash = sha256(raw_code),
            expires_at= utcnow() + timedelta(minutes=10),
        )
        db.add(otp)

        # Verify
        record = db.query(OTPVerification).filter(
            OTPVerification.user_id      == user.id,
            OTPVerification.purpose      == OTPPurpose.EMAIL_VERIFICATION,
            OTPVerification.consumed_at  == None,
            OTPVerification.expires_at   > utcnow(),
            OTPVerification.attempts     < OTPVerification.max_attempts,
        ).order_by(OTPVerification.created_at.desc()).first()

        if record and record.code_hash == sha256(submitted_code):
            record.consumed_at = utcnow()
            user.email_verified_at = utcnow()
            user.status = UserStatus.ACTIVE
        else:
            record.attempts += 1   # increment even on hash mismatch
    """

    __tablename__ = "otp_verifications"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True)

    # ── Who & why ─────────────────────────────────────────────────────────────
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="The user this OTP was issued for.",
    )

    purpose: Mapped[OTPPurpose] = mapped_column(
        otp_purpose_enum,
        nullable=False,
        comment=(
            "email_verification | password_reset | login_otp. "
            "Drives email template and expiry duration."
        ),
    )

    # ── The code (never stored plain) ─────────────────────────────────────────
    code_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment=(
            "SHA-256 of the raw 6-digit code. "
            "Raw code is emailed; only the hash is persisted."
        ),
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Hard expiry. Reject verification after this timestamp.",
    )

    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Set atomically on successful verification. NULL = not yet used.",
    )

    # ── Brute-force protection ────────────────────────────────────────────────
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="Incremented on every failed attempt. Reject when >= max_attempts.",
    )

    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        server_default=text("5"),
        comment="Maximum allowed wrong guesses before this OTP is invalidated.",
    )

    # ── Context (for audit / abuse detection) ────────────────────────────────
    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
        comment="IPv4 or IPv6 address of the request that triggered OTP issue.",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )

    # ── Relationship ──────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(  # noqa: F821
        "User",
        back_populates="otp_verifications",
        lazy="noload",
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        # Primary lookup: latest unconsumed OTP for a (user, purpose) pair.
        # Partial index excludes consumed rows — keeps it tiny and fast.
        Index(
            "ix_otp_user_purpose_active",
            "user_id",
            "purpose",
            postgresql_where=text("consumed_at IS NULL"),
        ),
        # Nightly cleanup job: DELETE WHERE expires_at < NOW() - '24h'.
        Index("ix_otp_expires", "expires_at"),
    )

    # ── Computed helpers ──────────────────────────────────────────────────────
    @property
    def is_valid(self) -> bool:
        """Quick check — service layer should also check code_hash."""
        from datetime import timezone
        return (
            self.consumed_at is None
            and self.attempts < self.max_attempts
            and self.expires_at > datetime.now(timezone.utc)
        )

    def __repr__(self) -> str:
        return (
            f"<OTPVerification user={self.user_id} "
            f"purpose={self.purpose} consumed={self.consumed_at is not None}>"
        )
