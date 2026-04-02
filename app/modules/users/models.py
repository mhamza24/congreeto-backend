# models/user.py
"""
User model — global table, no tenant_id.

One row per real human being. A person belongs to one or more tenants
via the tenant_users bridge table.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FLAT COLUMNS vs JSONB — Decision record for this table
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SHORT ANSWER: Use FLAT COLUMNS everywhere on this table. Do NOT use JSONB
for user profile data.

WHY:
1.  email         → WHERE, UNIQUE INDEX — must be flat.
2.  status        → WHERE status = 'active', ORDER BY — must be flat.
3.  first_name,
    last_name     → SELECT (display name), WHERE (admin search) — flat.
4.  last_login_at → ORDER BY, analytics — flat.
5.  avatar_url    → SELECT only (never filtered) — could technically be JSONB,
                    but a single VARCHAR is simpler; no JSONB benefit here.

JSONB IS WRONG for this table because:
- Every field here is individually queried, filtered, or indexed.
- JSONB shines only for config/metadata blobs that are ALWAYS read as
  a whole unit and NEVER individually filtered or sorted.
- Putting email/status/name in JSONB would force expensive
  (jsonb->>'email') expressions, disable index usage, and break
  type safety.

WHERE JSONB IS USED in this project:
- tenants.settings       (timezone, logo, etc. — whole-unit read)
- chatbot_configs.branding (bot_name, language — whole-unit read)
- user_settings table    (notification_prefs, ui_prefs — whole-unit read)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INDEXES — Decision record
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ix_users_public_id   — every API read is by public_id (never raw id)
ix_users_email       — login lookup; partial (deleted_at IS NULL)
ix_users_email_hash  — chatbot returning-visitor lookup (no join needed)
ix_users_status      — admin dashboards filter by status; partial

No index on first_name / last_name:
  Admin search uses ILIKE '%smith%' — a B-tree won't help.
  Add a pg_trgm GIN index if full-text search is needed later.

No index on avatar_url / password_hash:
  Never queried. Index overhead not justified.

No index on last_login_at at this layer:
  Analytics queries on this column go through the read replica / DW.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, String, Index, text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_base import Base, PublicIdMixin, TimestampMixin, SoftDeleteMixin
from app.core.enums import UserStatus, user_status_enum
from app.modules.models.otp import OTPVerification
from app.modules.models.tenant_user import TenantUser


class User(Base, PublicIdMixin, TimestampMixin, SoftDeleteMixin):
    """
    Global user record. No tenant_id here.
    Tenant membership lives in TenantUser (bridge table).

    Security notes:
    - password_hash: bcrypt/argon2 output only. NEVER store plain-text.
    - email_hash:    SHA-256(lower(email)). Used for chatbot visitor
                     re-identification without exposing raw email to
                     the embedding JS or cross-tenant queries.
    - The integer `id` is NEVER returned by any API endpoint.
      All external references use `public_id`.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True)

    # ── Core identity (all flat — see module docstring) ───────────────────────
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        comment="Globally unique. Lowercased before insert.",
    )

    email_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
        comment=(
            "SHA-256(lower(email)). "
            "Used to match returning chatbot visitors to a registered user "
            "without exposing raw email. Never recalculate from ORM — "
            "set explicitly in the service layer before insert."
        ),
    )

    # ── Auth ──────────────────────────────────────────────────────────────────
    password_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default=None,
        comment="NULL for OAuth-only or magic-link-only accounts.",
    )

    # ── Profile ───────────────────────────────────────────────────────────────
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    avatar_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Absolute URL to avatar image in S3/CDN.",
    )

    # ── Status & verification ─────────────────────────────────────────────────
    status: Mapped[UserStatus] = mapped_column(
        user_status_enum,
        nullable=False,
        default=UserStatus.INVITED,
        server_default=text("'invited'"),
        comment=(
            "invited=email not verified | active=verified | "
            "inactive=deactivated | suspended=locked"
        ),
    )

    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment=(
            "Populated when the user successfully verifies their email "
            "via OTP or magic link. NULL means unverified."
        ),
    )

    # ── Activity ──────────────────────────────────────────────────────────────
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Updated on every successful authentication.",
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    tenant_users: Mapped[list["TenantUser"]] = relationship(  # noqa: F821
        "TenantUser",
        back_populates="user",
        lazy="noload",
        foreign_keys="TenantUser.user_id",
    )

    otp_verifications: Mapped[list["OTPVerification"]] = relationship(  # noqa: F821
        "OTPVerification",
        back_populates="user",
        lazy="noload",
        cascade="all, delete-orphan",
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        # Every API read is by public_id — covered by PublicIdMixin unique index,
        # but we name it explicitly for pg_stat_user_indexes visibility.
        Index("ix_users_public_id", "public_id"),

        # Login lookup. Partial: skip soft-deleted users.
        Index(
            "ix_users_email",
            "email",
            postgresql_where=text("deleted_at IS NULL"),
        ),

        # Returning chatbot visitor lookup.
        Index("ix_users_email_hash", "email_hash"),

        # Admin dashboard filter. Partial: skip soft-deleted.
        Index(
            "ix_users_status",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    # ── Computed helpers ──────────────────────────────────────────────────────
    @property
    def full_name(self) -> str:
        parts = filter(None, [self.first_name, self.last_name])
        return " ".join(parts) or self.email

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None

    def __repr__(self) -> str:
        return (
            f"<User id={self.id} email={self.email!r} status={self.status}>"
        )
