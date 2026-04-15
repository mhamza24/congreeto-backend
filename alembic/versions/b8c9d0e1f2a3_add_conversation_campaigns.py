"""add conversation_campaigns junction table

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-04-15

Adds the conversation_campaigns many-to-many table so a single conversation
can be linked to multiple campaigns.

Previously conversations held a single campaign_id FK (kept for backward
compatibility). This table is the authoritative source for the full list of
campaigns matched when the conversation started.
"""

from alembic import op
import sqlalchemy as sa

revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'conversation_campaigns',

        sa.Column(
            'conversation_id',
            sa.BigInteger(),
            sa.ForeignKey('conversations.id', ondelete='CASCADE'),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            'campaign_id',
            sa.BigInteger(),
            sa.ForeignKey('campaigns.id', ondelete='CASCADE'),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            'matched_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(NOW() AT TIME ZONE 'UTC')"),
            comment='Timestamp when this campaign was matched to the conversation.',
        ),

        sa.PrimaryKeyConstraint('conversation_id', 'campaign_id'),
    )

    op.create_index('ix_conv_campaigns_conv',     'conversation_campaigns', ['conversation_id'])
    op.create_index('ix_conv_campaigns_campaign', 'conversation_campaigns', ['campaign_id'])


def downgrade() -> None:
    op.drop_index('ix_conv_campaigns_campaign', table_name='conversation_campaigns')
    op.drop_index('ix_conv_campaigns_conv',     table_name='conversation_campaigns')
    op.drop_table('conversation_campaigns')
