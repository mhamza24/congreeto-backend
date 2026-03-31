# models/base.py
"""
Declarative base and reusable mixins.
 
TimestampMixin  — created_at / updated_at auto-managed by SQLAlchemy.
SoftDeleteMixin — deleted_at for soft-deletes; use with WHERE deleted_at IS NULL.
PublicIdMixin   — exposes public_id (uuid7-style) separately from integer PK.
"""
from __future__ import annotations
from pydantic import BaseModel
from sqlalchemy import inspect
from sqlalchemy.orm import DeclarativeBase
from uuid6 import uuid7
import uuid
from datetime import datetime, timezone
 
from sqlalchemy import DateTime, String, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
 
class Base(DeclarativeBase):
     @classmethod
     def from_schema(cls, schema: BaseModel, **overrides):
        """
        Dynamically maps a Pydantic schema onto a SQLAlchemy model.
        Only sets fields that exist as columns on the model.
        Pass overrides for fields that need transformation before saving
        (e.g. password_hash, email_hash).

        Usage:
            user = User.from_schema(payload, password_hash=hashed, email_hash=hashed_email)
        """
        model_columns = {c.key for c in inspect(cls).mapper.column_attrs}
        schema_data   = schema.model_dump(exclude_unset=False)

        data = {
            key: val
            for key, val in schema_data.items()
            if key in model_columns
        }
        data.update(overrides)   # overrides win over schema values
        return cls(**data)

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
 
 
def _new_public_id() -> str:
    """
    Generates a uuid7 string as the public identifier.
    """
    return str(uuid7())
 

 
 
class TimestampMixin:
    """
    Adds created_at / updated_at columns managed at the Python layer.
 
    Use server_default for created_at so it is also correct when rows are
    inserted via raw SQL (e.g., Alembic data migrations).
    onupdate fires on every ORM flush; set explicitly when doing bulk updates.
    """
 
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("NOW()"),
        index=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("NOW()"),
    )
 
 
class SoftDeleteMixin:
    """
    Adds deleted_at for soft-deletion.
    All queries against soft-deletable tables MUST filter WHERE deleted_at IS NULL.
    Partial indexes on the real tables already enforce this.
    """
 
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
    )
 
    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
 
 
class PublicIdMixin:
    """
    Adds public_id (uuid4/uuid7 string) as a unique, non-sequential public key.
    The integer PK (id) is NEVER exposed in API responses or URLs.
    """
 
    public_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        unique=True,
        default=_new_public_id,
        index=True,
    )
 