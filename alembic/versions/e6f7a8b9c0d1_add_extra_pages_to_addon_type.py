"""add extra_pages to addon_type enum

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-04-14

Adds 'extra_pages' value to the addon_type PostgreSQL enum.
Safe zero-downtime operation — no table rewrite needed (PG 10+).
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE addon_type ADD VALUE IF NOT EXISTS 'extra_pages'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values.
    # To roll back: recreate the enum without 'extra_pages' and migrate the column.
    pass
