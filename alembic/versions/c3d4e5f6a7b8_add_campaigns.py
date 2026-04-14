"""add campaigns table and conversation campaign_id

Revision ID: c3d4e5f6a7b8
Revises: (d4e5f6a7b8c9, a1b2c3d4e5f6)
Create Date: 2026-04-14

Merges the two existing heads (d4e5f6a7b8c9 add_two_fa, a1b2c3d4e5f6 add_otp_purpose)
and adds the campaigns feature on top.

Changes
───────
1. CREATE TYPE campaign_status AS ENUM ('draft', 'active', 'inactive')
2. CREATE TABLE campaigns  (url-pattern matching, prompt overlay, no iframe_token)
3. ALTER TABLE conversations ADD COLUMN campaign_id (nullable FK → campaigns.id)
4. ALTER TABLE conversations ADD COLUMN page_url (if not already present)
5. Data migration: add max_campaigns to existing plans that don't have it yet
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = ('d4e5f6a7b8c9', 'a1b2c3d4e5f6')
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create Postgres ENUM type ─────────────────────────────────────────
    op.execute("CREATE TYPE campaign_status AS ENUM ('draft', 'active', 'inactive')")

    # ── 2. Create campaigns table ─────────────────────────────────────────────
    op.create_table(
        'campaigns',

        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('public_id', sa.String(), nullable=False, comment='External identifier (uuid7).'),

        # Ownership
        sa.Column(
            'tenant_id', sa.BigInteger(), nullable=False,
            comment='Denormalized — avoids joining chatbot_configs for tenant-scoped queries.',
        ),
        sa.Column(
            'chatbot_config_id', sa.BigInteger(), nullable=False,
            comment='The base chatbot this campaign overlays.',
        ),

        # Identity
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),

        # Status
        sa.Column(
            'status',
            postgresql.ENUM('draft', 'active', 'inactive', name='campaign_status', create_type=False),
            nullable=False,
            server_default='draft',
        ),

        # URL targeting
        sa.Column(
            'url_patterns',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment=(
                "List of URL substrings that trigger this campaign. "
                "Case-insensitive substring match against visitor page_url. "
                "Empty list = no URL targeting (see is_default)."
            ),
        ),
        sa.Column(
            'is_default',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Catch-all fallback when no url_patterns match. One per chatbot.',
        ),
        sa.Column(
            'sort_order',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Lower = higher priority when multiple campaigns match the same URL.',
        ),

        # Prompt overlay
        sa.Column(
            'prompt_overlay',
            sa.Text(),
            nullable=True,
            comment='Injected between static base and dynamic RAG suffix at chat time.',
        ),

        # Timestamps
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("(NOW() AT TIME ZONE 'UTC')"),
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("(NOW() AT TIME ZONE 'UTC')"),
        ),

        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('public_id'),
        sa.ForeignKeyConstraint(
            ['tenant_id'], ['tenants.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['chatbot_config_id'], ['chatbot_configs.id'],
            ondelete='CASCADE',
        ),
    )

    # ── Indexes on campaigns ──────────────────────────────────────────────────
    op.create_index('ix_campaigns_tenant',         'campaigns', ['tenant_id'])
    op.create_index('ix_campaigns_chatbot',        'campaigns', ['chatbot_config_id'])
    op.create_index('ix_campaigns_tenant_status',  'campaigns', ['tenant_id', 'status'])
    op.create_index('ix_campaigns_chatbot_status', 'campaigns', ['chatbot_config_id', 'status'])
    op.create_index('ix_campaigns_public_id',      'campaigns', ['public_id'], unique=True)

    # ── 3. Add campaign_id to conversations ───────────────────────────────────
    op.add_column(
        'conversations',
        sa.Column(
            'campaign_id',
            sa.BigInteger(),
            sa.ForeignKey('campaigns.id', ondelete='SET NULL'),
            nullable=True,
            comment=(
                "Campaign active at conversation start. SET NULL when campaign is deleted "
                "so historical conversations are preserved. NULL = no campaign (base chatbot)."
            ),
        ),
    )
    op.create_index('ix_conversations_campaign', 'conversations', ['campaign_id'])

    # ── 4. Data migration — add max_campaigns to existing plans ─────────────
    # Note: page_url already exists on conversations from a prior migration.
    op.execute(
        """
        UPDATE plans
        SET limits = limits || '{"max_campaigns": 5}'::jsonb
        WHERE limits->>'max_campaigns' IS NULL
        """
    )


def downgrade() -> None:
    # Data migration not reversed (limits JSONB is additive).
    # page_url pre-existed — not dropped here.

    # Reverse campaign_id
    op.drop_index('ix_conversations_campaign', table_name='conversations')
    op.drop_column('conversations', 'campaign_id')

    # Reverse 2
    op.drop_index('ix_campaigns_public_id',      table_name='campaigns')
    op.drop_index('ix_campaigns_chatbot_status', table_name='campaigns')
    op.drop_index('ix_campaigns_tenant_status',  table_name='campaigns')
    op.drop_index('ix_campaigns_chatbot',        table_name='campaigns')
    op.drop_index('ix_campaigns_tenant',         table_name='campaigns')
    op.drop_table('campaigns')

    # Reverse 1
    op.execute("DROP TYPE campaign_status")
