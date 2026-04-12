"""
app/modules/audit/models.py

Append-only audit trail.  NEVER UPDATE or DELETE rows here.
Written to match the exact schema agreed in the DB spec.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_base import Base


class AuditLog(Base):
    """
    Forensic trail of every meaningful state change in the platform.

    Rules (enforced by convention — the DB has no UPDATE/DELETE triggers):
      - Rows are INSERT-only.  Never call session.delete() or UPDATE on this table.
      - tenant_id / user_id are nullable: platform-level or system actions have no
        tenant or user context.
      - ON DELETE SET NULL: deleting a tenant/user preserves the audit history.
      - diff should always be { "before": {...}, "after": {...} }.
        Pass {} when there is no meaningful diff (e.g. pure CREATE actions).
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # NULL for platform-level actions (no tenant context)
    tenant_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        default=None,
        comment="NULL for platform-level actions. ON DELETE SET NULL preserves history.",
    )

    # NULL for system-triggered actions (no user context)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        default=None,
        comment="NULL for system-triggered actions. ON DELETE SET NULL preserves history.",
    )

    entity_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment='Table name being acted on, e.g. "listings", "tenants", "users".',
    )

    entity_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="PK of the affected row.  NULL for bulk/schema-level actions.",
    )

    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment='Verb: create | update | delete | suspend | restore | login | logout | etc.',
    )

    # { "before": { "status": "active" }, "after": { "status": "suspended" } }
    diff: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        comment='JSON diff. Always { "before": {...}, "after": {...} }. {} for pure creates.',
    )

    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
        comment="IPv4 or IPv6 address of the requesting client.",
    )

    user_agent: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="HTTP User-Agent header of the requesting client.",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("NOW()"),
        comment="UTC timestamp. Set once on INSERT, never changed.",
    )

    # ── Indexes (matches exact SQL in the DB spec) ────────────────────────────
    __table_args__ = (
        Index(
            "ix_audit_tenant",
            "tenant_id",
            "created_at",
            postgresql_where=text("tenant_id IS NOT NULL"),
        ),
        Index(
            "ix_audit_entity",
            "entity_type",
            "entity_id",
        ),
        Index(
            "ix_audit_user",
            "user_id",
            "created_at",
            postgresql_where=text("user_id IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} "
            f"entity={self.entity_type}:{self.entity_id} "
            f"action={self.action}>"
        )
