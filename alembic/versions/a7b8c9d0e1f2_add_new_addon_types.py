"""add extra_tokens, extra_chatbots, custom_banner, extra_ribbon_messages to addon_type

Revision ID: a7b8c9d0e1f2
Revises: e6f7a8b9c0d1
Create Date: 2026-04-15

Adds 4 new values to the addon_type PostgreSQL enum.
Safe zero-downtime operation — no table rewrite needed (PG 10+).
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE addon_type ADD VALUE IF NOT EXISTS 'extra_tokens'")
    op.execute("ALTER TYPE addon_type ADD VALUE IF NOT EXISTS 'extra_chatbots'")
    op.execute("ALTER TYPE addon_type ADD VALUE IF NOT EXISTS 'custom_banner'")
    op.execute("ALTER TYPE addon_type ADD VALUE IF NOT EXISTS 'extra_ribbon_messages'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values.
    # To roll back: recreate the enum without these values and migrate the column.
    pass
