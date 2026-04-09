"""add_tenant_invite_otp_purpose

Revision ID: a1b2c3d4e5f6
Revises: 16ffb7ba9703
Create Date: 2026-04-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '16ffb7ba9703'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block in Postgres.
    # execute_if ensures it only runs on postgresql.
    op.execute("ALTER TYPE otp_purpose ADD VALUE IF NOT EXISTS 'tenant_invite';")


def downgrade() -> None:
    # Postgres does not support removing enum values directly.
    # We recreate the type without 'tenant_invite' and swap the column.
    op.execute("""
        DELETE FROM otp_verifications WHERE purpose = 'tenant_invite';
    """)
    op.execute("""
        ALTER TYPE otp_purpose RENAME TO otp_purpose_old;
    """)
    op.execute("""
        CREATE TYPE otp_purpose AS ENUM (
            'email_verification',
            'password_reset',
            'login_otp'
        );
    """)
    op.execute("""
        ALTER TABLE otp_verifications
            ALTER COLUMN purpose TYPE otp_purpose
            USING purpose::text::otp_purpose;
    """)
    op.execute("DROP TYPE otp_purpose_old;")
