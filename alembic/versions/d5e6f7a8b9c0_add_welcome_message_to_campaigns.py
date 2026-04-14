"""add welcome_message to campaigns

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-04-14

Adds the welcome_message column to the campaigns table.
When a campaign is matched for a page URL this message is shown in the
chatbot widget instead of the chatbot-level welcome_message.
NULL = fall back to the chatbot's welcome_message.
"""

from alembic import op
import sqlalchemy as sa

revision = 'd5e6f7a8b9c0'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'campaigns',
        sa.Column(
            'welcome_message',
            sa.Text(),
            nullable=True,
            comment=(
                "First message shown in the chatbot widget when a visitor lands on a page "
                "matched by this campaign. Overrides the chatbot-level welcome_message. "
                "NULL = fall back to the chatbot welcome_message."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column('campaigns', 'welcome_message')
