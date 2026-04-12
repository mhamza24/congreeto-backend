"""add_audit_logs_table

Revision ID: f1a2b3c4d5e6
Revises: 3518a9ffca52
Create Date: 2026-04-12 00:00:00.000000

Append-only forensic audit trail.
NEVER add UPDATE or DELETE statements against this table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "3518a9ffca52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
            comment="NULL for platform-level actions. ON DELETE SET NULL preserves history.",
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            comment="NULL for system-triggered actions. ON DELETE SET NULL preserves history.",
        ),
        sa.Column(
            "entity_type",
            sa.String(length=100),
            nullable=False,
            comment='Table name being acted on, e.g. "listings", "tenants".',
        ),
        sa.Column(
            "entity_id",
            sa.BigInteger(),
            nullable=True,
            comment="PK of the affected row. NULL for bulk/schema-level actions.",
        ),
        sa.Column(
            "action",
            sa.String(length=50),
            nullable=False,
            comment="Verb: create | update | delete | suspend | restore | login | logout | etc.",
        ),
        sa.Column(
            "diff",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment='JSON diff. Always { "before": {...}, "after": {...} }.',
        ),
        sa.Column(
            "ip_address",
            sa.String(length=45),
            nullable=True,
            comment="IPv4 or IPv6 address of the requesting client.",
        ),
        sa.Column(
            "user_agent",
            sa.Text(),
            nullable=True,
            comment="HTTP User-Agent header of the requesting client.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="UTC timestamp. Set once on INSERT, never changed.",
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="Append-only. Never UPDATE or DELETE. ON DELETE SET NULL preserves history.",
    )

    # Partial index on tenant_id — only for rows that have a tenant
    op.create_index(
        "ix_audit_tenant",
        "audit_logs",
        ["tenant_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )

    # Entity lookup — find all audit events for a specific row
    op.create_index(
        "ix_audit_entity",
        "audit_logs",
        ["entity_type", "entity_id"],
    )

    # Partial index on user_id — only for rows that have a user
    op.create_index(
        "ix_audit_user",
        "audit_logs",
        ["user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_audit_user", table_name="audit_logs")
    op.drop_index("ix_audit_entity", table_name="audit_logs")
    op.drop_index("ix_audit_tenant", table_name="audit_logs")
    op.drop_table("audit_logs")
