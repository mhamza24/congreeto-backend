"""add listing_upload_jobs table

Revision ID: b7c8d9e0f1a2
Revises: ac198940e2dd
Create Date: 2026-04-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, None] = 'ac198940e2dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'listing_upload_jobs',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column('public_id', sa.String(36), nullable=False),
        sa.Column('tenant_id', sa.BigInteger(), nullable=False),
        sa.Column('filename', sa.String(500), nullable=False),
        sa.Column('file_type', sa.String(10), nullable=False),
        sa.Column('file_data', sa.LargeBinary(), nullable=True),
        sa.Column('storage_path', sa.String(1000), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('total_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('processed_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(NOW() AT TIME ZONE 'UTC')"),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(NOW() AT TIME ZONE 'UTC')"),
        ),
        sa.UniqueConstraint('public_id', name='uq_listing_upload_jobs_public_id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_listing_upload_jobs_tenant', 'listing_upload_jobs', ['tenant_id'])
    op.create_index('ix_listing_upload_jobs_status', 'listing_upload_jobs', ['status'])


def downgrade() -> None:
    op.drop_index('ix_listing_upload_jobs_status', table_name='listing_upload_jobs')
    op.drop_index('ix_listing_upload_jobs_tenant', table_name='listing_upload_jobs')
    op.drop_table('listing_upload_jobs')
