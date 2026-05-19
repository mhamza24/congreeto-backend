"""change_currency_default_to_usd

Changes the server-side default for all currency columns from 'AUD' to 'USD'.
Affects: tenant_subscriptions, tenant_addon_subscriptions, user_subscriptions, listings.

Existing rows are NOT updated — only new rows inserted without an explicit
currency value will default to USD going forward.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-20
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "tenant_subscriptions", "currency",
        server_default="USD",
    )
    op.alter_column(
        "tenant_addon_subscriptions", "currency",
        server_default="USD",
    )
    op.alter_column(
        "user_subscriptions", "currency",
        server_default="USD",
    )
    op.alter_column(
        "listings", "currency",
        server_default="USD",
    )


def downgrade() -> None:
    op.alter_column(
        "tenant_subscriptions", "currency",
        server_default="AUD",
    )
    op.alter_column(
        "tenant_addon_subscriptions", "currency",
        server_default="AUD",
    )
    op.alter_column(
        "user_subscriptions", "currency",
        server_default="AUD",
    )
    op.alter_column(
        "listings", "currency",
        server_default="AUD",
    )
