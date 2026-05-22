"""add chatbot model column and EXTRA_PREMIUM_MODEL addon type

Revision ID: f7a8b9c0d1e2
Revises: e1f2a3b4c5d6
Create Date: 2026-05-23
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-chatbot model override. NULL = use platform default (gpt-4o-mini).
    op.add_column(
        "chatbot_configs",
        sa.Column(
            "model",
            sa.String(64),
            nullable=True,
            comment=(
                "OpenAI chat model override. NULL = use settings.OPEN_AI_MODEL. "
                "Only premium values allowed if tenant has the Premium AI add-on."
            ),
        ),
    )

    # Postgres enum: add new value to existing addon_type enum (must commit before reuse).
    op.execute("ALTER TYPE addon_type ADD VALUE IF NOT EXISTS 'extra_premium_model'")


def downgrade() -> None:
    op.drop_column("chatbot_configs", "model")
    # Note: Postgres does not support removing enum values cleanly without
    # recreating the type. Leaving 'extra_premium_model' in the enum on downgrade
    # is the standard safe practice.
