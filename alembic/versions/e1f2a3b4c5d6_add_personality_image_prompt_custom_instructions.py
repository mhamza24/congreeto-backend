"""add personality image, system_prompt, and chatbot custom_instructions

Revision ID: e1f2a3b4c5d6
Revises: d1e2f3a4b5c6
Create Date: 2026-05-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── prompt_personalities ─────────────────────────────────────────────────
    op.add_column(
        "prompt_personalities",
        sa.Column("image_url", sa.String(2048), nullable=True,
                  comment="URL of the personality avatar/icon image."),
    )
    op.add_column(
        "prompt_personalities",
        sa.Column("image_data", sa.LargeBinary, nullable=True,
                  comment="Raw bytes of the uploaded personality image."),
    )
    op.add_column(
        "prompt_personalities",
        sa.Column("image_content_type", sa.String(100), nullable=True,
                  comment="MIME type of the uploaded image, e.g. image/png."),
    )
    op.add_column(
        "prompt_personalities",
        sa.Column(
            "system_prompt",
            sa.Text,
            nullable=True,
            comment=(
                "Plain-text system prompt for admin-created personalities. "
                "When set, takes precedence over personality_content JSONB rendering."
            ),
        ),
    )

    # ── chatbot_configs ──────────────────────────────────────────────────────
    op.add_column(
        "chatbot_configs",
        sa.Column(
            "custom_instructions",
            sa.Text,
            nullable=True,
            comment=(
                "Tenant-supplied override instructions appended after the base "
                "personality block in the system prompt. "
                "e.g. 'Be more sales-driven and push towards closing.'"
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("chatbot_configs", "custom_instructions")
    op.drop_column("prompt_personalities", "system_prompt")
    op.drop_column("prompt_personalities", "image_content_type")
    op.drop_column("prompt_personalities", "image_data")
    op.drop_column("prompt_personalities", "image_url")
