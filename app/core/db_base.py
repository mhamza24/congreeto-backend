# app/core/db_base.py
"""
Declarative base and reusable mixins.

TimestampMixin  — created_at / updated_at auto-managed by SQLAlchemy.
SoftDeleteMixin — deleted_at for soft-deletes; use with WHERE deleted_at IS NULL.
PublicIdMixin   — exposes public_id (uuid7-style) separately from integer PK.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import DateTime, String, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid6 import uuid7


# =============================================================================
# HELPERS
# =============================================================================

def _utcnow() -> datetime:
    """Always returns timezone-aware UTC datetime. Never use datetime.now() or datetime.utcnow()."""
    return datetime.now(timezone.utc)


def _new_public_id() -> str:
    """
    Generates a uuid7 string as the public identifier.
    uuid7 is time-sortable and non-predictable — safe to expose in APIs and URLs.
    """
    return str(uuid7())


# =============================================================================
# BASE
# =============================================================================

class Base(DeclarativeBase):
    @classmethod
    def from_schema(cls, schema: BaseModel, **overrides):
        """
        Dynamically maps a Pydantic schema onto a SQLAlchemy model.
        Only sets fields that exist as columns on the model.
        Pass overrides for fields that need transformation before saving.

        Usage:
            user = User.from_schema(payload, password_hash=hashed, email_hash=hashed_email)
            tenant = Tenant.from_schema(payload, status=TenantStatus.PENDING_PLAN)
        """
        model_columns = {c.key for c in inspect(cls).mapper.column_attrs}
        schema_data   = schema.model_dump(exclude_unset=False)

        data = {
            key: val
            for key, val in schema_data.items()
            if key in model_columns
        }
        data.update(overrides)  # overrides always win over schema values
        return cls(**data)


# =============================================================================
# MIXINS
# =============================================================================

class TimestampMixin:
    """
    Adds created_at / updated_at columns managed at the Python layer.

    created_at:
        - default=_utcnow        → set by Python ORM on INSERT
        - server_default         → set by Postgres on raw SQL INSERT
                                   (e.g. Alembic data migrations)
        - Both always produce UTC

    updated_at:
        - default=_utcnow        → set by Python ORM on INSERT
        - onupdate=_utcnow       → auto-updated by Python ORM on every flush
        - server_default         → set by Postgres on raw SQL INSERT
        - For bulk UPDATE via raw SQL: set updated_at explicitly

    server_default uses (NOW() AT TIME ZONE 'UTC') with parentheses
    because PostgreSQL requires expressions in CREATE TABLE DEFAULT
    to be wrapped in parentheses.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("(NOW() AT TIME ZONE 'UTC')"),
        index=False,
        comment="UTC timestamp set on INSERT. Never modified after creation.",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("(NOW() AT TIME ZONE 'UTC')"),
        comment="UTC timestamp auto-updated by ORM on every flush.",
    )


class SoftDeleteMixin:
    """
    Adds deleted_at for soft-deletion.

    Rules:
    - All queries against soft-deletable tables MUST filter WHERE deleted_at IS NULL.
    - Partial indexes on individual tables enforce this at the DB level.
    - To soft-delete: record.deleted_at = datetime.now(timezone.utc)
    - To restore:     record.deleted_at = None
    - Hard delete is never used on soft-deletable tables.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
        comment="NULL = active record. Non-NULL = soft-deleted. Always set to UTC.",
    )

    @property
    def is_deleted(self) -> bool:
        """True if this record has been soft-deleted."""
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        """Convenience method — always uses UTC."""
        self.deleted_at = _utcnow()

    def restore(self) -> None:
        """Undo a soft-delete."""
        self.deleted_at = None


class PublicIdMixin:
    """
    Adds public_id (uuid7 string) as a unique, non-sequential external identifier.

    Rules:
    - The integer PK (id) is NEVER exposed in API responses or URLs.
    - public_id is used in all external references (URL paths, API responses).
    - uuid7 is time-sortable: ORDER BY public_id ≈ ORDER BY created_at.
    - uuid7 is non-predictable: clients cannot enumerate records.
    """

    public_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        unique=True,
        default=_new_public_id,
        index=True,
        comment=(
            "External identifier (uuid7). "
            "Time-sortable and non-predictable. "
            "Only this ID is exposed in API responses — never the integer PK."
        ),
    )