"""fix listing_upload_jobs status column to varchar

Revision ID: c9f0a1b2d3e4
Revises: b7c8d9e0f1a2
Create Date: 2026-04-10 17:00:00.000000

Fixes the status column on listing_upload_jobs:
- If the table does not exist yet, creates it with VARCHAR status.
- If the table exists with status typed as a native PG enum,
  converts it to VARCHAR(20) and drops the orphaned enum type.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c9f0a1b2d3e4'
down_revision: Union[str, None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Check whether the table exists at all
    table_exists = conn.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'listing_upload_jobs'
        )
    """)).scalar()

    if not table_exists:
        # Table was never created — create it now with VARCHAR status
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
                'created_at', sa.DateTime(timezone=True), nullable=False,
                server_default=sa.text("(NOW() AT TIME ZONE 'UTC')"),
            ),
            sa.Column(
                'updated_at', sa.DateTime(timezone=True), nullable=False,
                server_default=sa.text("(NOW() AT TIME ZONE 'UTC')"),
            ),
            sa.UniqueConstraint('public_id', name='uq_listing_upload_jobs_public_id'),
            sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_listing_upload_jobs_tenant', 'listing_upload_jobs', ['tenant_id'])
        op.create_index('ix_listing_upload_jobs_status', 'listing_upload_jobs', ['status'])
    else:
        # Table exists — check if status column is still a native PG enum type
        col_type = conn.execute(sa.text("""
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'listing_upload_jobs' AND column_name = 'status'
        """)).scalar()

        if col_type and col_type != 'character varying':
            # Convert from native enum to VARCHAR
            op.execute(sa.text("""
                ALTER TABLE listing_upload_jobs
                    ALTER COLUMN status TYPE VARCHAR(20)
                    USING status::text
            """))

    # Drop the orphaned PG enum type if it exists
    conn.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'upload_job_status') THEN
                DROP TYPE upload_job_status;
            END IF;
        END $$;
    """))


def downgrade() -> None:
    # Nothing to reverse — VARCHAR is the intended final state
    pass
