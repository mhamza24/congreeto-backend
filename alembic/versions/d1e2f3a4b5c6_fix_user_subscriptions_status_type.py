"""fix_user_subscriptions_status_type

The user_subscriptions.status column was created with type name
'subscriptionstatus' (no underscore) but the SQLAlchemy model uses the shared
'subscription_status' enum (with underscore). This causes asyncpg to raise
"operator does not exist: subscriptionstatus = subscription_status" on every
query that filters by status.

Fix: cast the column to the correct 'subscription_status' type and drop the
orphaned 'subscriptionstatus' type.

Revision ID: d1e2f3a4b5c6
Revises: b1c2d3e4f5a6
Create Date: 2026-05-20
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_subscriptions ALTER COLUMN status DROP DEFAULT")
    op.execute(
        """
        ALTER TABLE user_subscriptions
        ALTER COLUMN status TYPE subscription_status
        USING status::text::subscription_status
        """
    )
    op.execute("ALTER TABLE user_subscriptions ALTER COLUMN status SET DEFAULT 'active'::subscription_status")
    op.execute("DROP TYPE IF EXISTS subscriptionstatus")


def downgrade() -> None:
    op.execute(
        """
        CREATE TYPE subscriptionstatus AS ENUM
        ('trialing', 'active', 'past_due', 'cancelled', 'paused')
        """
    )
    op.execute("ALTER TABLE user_subscriptions ALTER COLUMN status DROP DEFAULT")
    op.execute(
        """
        ALTER TABLE user_subscriptions
        ALTER COLUMN status TYPE subscriptionstatus
        USING status::text::subscriptionstatus
        """
    )
    op.execute("ALTER TABLE user_subscriptions ALTER COLUMN status SET DEFAULT 'active'::subscriptionstatus")
