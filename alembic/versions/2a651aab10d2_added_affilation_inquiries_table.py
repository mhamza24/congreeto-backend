"""added affilation inquiries table

Revision ID: 2a651aab10d2
Revises: e7b18c1449fa
Create Date: 2026-03-24 13:40:17.986231

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '2a651aab10d2'
down_revision: Union[str, None] = 'e7b18c1449fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('affiliation_inquiries',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('public_id', sa.String(), nullable=False, comment='External identifier (uuid7)'),
    sa.Column('first_name', sa.String(), nullable=False),
    sa.Column('last_name', sa.String(), nullable=False),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('phone', sa.String(), nullable=True),
    sa.Column('category', sa.String(), nullable=True, comment='Applicant category: individual, agency, or any future value'),
    sa.Column('abn', sa.String(), nullable=True, comment='Australian Business Number (11 digits, stored as string to preserve leading zeros)'),
    sa.Column('acn', sa.String(), nullable=True, comment='Australian Company Number (9 digits, stored as string)'),
    sa.Column('legal_entity_name', sa.String(), nullable=True),
    sa.Column('gst_applicable', sa.String(), nullable=True, comment='GST registration status: yes, no, or future values'),
    sa.Column('company_type', sa.String(), nullable=True, comment='Business structure type: sole_trader, private_ltd, trust, etc.'),
    sa.Column('status', postgresql.ENUM(
        'submitted', 'reviewed', 'contacted', 'qualified', 'converted', 'archived',
        name='inquirystatus',
        create_type=False,  # ← type already exists in DB from earlier migrations
    ), nullable=False),
    sa.Column('visitor_ip_hash', sa.String(), nullable=True),
    sa.Column('visitor_ua', sa.String(), nullable=True),
    sa.Column('page_url', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('public_id')
    )
    op.create_index('ix_affiliation_inquiries_abn', 'affiliation_inquiries', ['abn'], unique=False)
    op.create_index('ix_affiliation_inquiries_created_at', 'affiliation_inquiries', ['created_at'], unique=False)
    op.create_index('ix_affiliation_inquiries_email', 'affiliation_inquiries', ['email'], unique=False)
    op.create_index('ix_affiliation_inquiries_public_id', 'affiliation_inquiries', ['public_id'], unique=False)
    op.create_index('ix_affiliation_inquiries_status', 'affiliation_inquiries', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_affiliation_inquiries_status', table_name='affiliation_inquiries')
    op.drop_index('ix_affiliation_inquiries_public_id', table_name='affiliation_inquiries')
    op.drop_index('ix_affiliation_inquiries_email', table_name='affiliation_inquiries')
    op.drop_index('ix_affiliation_inquiries_created_at', table_name='affiliation_inquiries')
    op.drop_index('ix_affiliation_inquiries_abn', table_name='affiliation_inquiries')
    op.drop_table('affiliation_inquiries')
    # NOTE: intentionally NOT dropping the inquirystatus type —
    # it is shared with general_inquiries and demo_inquiries tables