"""add_user_subscriptions

Adds the user_subscriptions table for platform-level (pre-tenant) billing.

The user buys a plan from the paywall (no tenant yet). Once paid, they can
create tenants up to the plan's max_tenants limit.

Revision ID: b1c2d3e4f5a6
Revises: a9b8c7d6e5f4
Create Date: 2026-05-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Re-use the existing DB-level enum — do NOT create a new one.
subscription_status_enum = sa.Enum(
    "trialing", "active", "past_due", "cancelled", "paused",
    name="subscriptionstatus",
    create_type=False,  # already exists from the billing tables migration
)


def upgrade() -> None:
    op.create_table(
        "user_subscriptions",
        sa.Column("id",           sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id",    sa.String(),     nullable=False),
        sa.Column("user_id",      sa.BigInteger(), nullable=False),
        sa.Column("plan_id",      sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            subscription_status_enum,
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("currency",              sa.String(3),            nullable=False, server_default=sa.text("'AUD'")),
        sa.Column("current_period_start",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end",    sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_ends_at",         sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at",          sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end",  sa.Boolean(),            nullable=False, server_default=sa.text("FALSE")),
        sa.Column("notes",                 sa.Text(),               nullable=True),
        sa.Column("stripe_subscription_id", sa.String(255),         nullable=True),
        sa.Column("stripe_customer_id",     sa.String(255),         nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),

        sa.ForeignKeyConstraint(["user_id"], ["users.id"],  ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("stripe_subscription_id", name="uq_user_sub_stripe_id"),
    )

    op.create_index("ix_user_subs_user",   "user_subscriptions", ["user_id"])
    op.create_index("ix_user_subs_status", "user_subscriptions", ["status"])
    op.create_index("ix_user_subs_stripe", "user_subscriptions", ["stripe_subscription_id"])


def downgrade() -> None:
    op.drop_index("ix_user_subs_stripe", table_name="user_subscriptions")
    op.drop_index("ix_user_subs_status", table_name="user_subscriptions")
    op.drop_index("ix_user_subs_user",   table_name="user_subscriptions")
    op.drop_table("user_subscriptions")
