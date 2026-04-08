"""add_tenant_user_status

Revision ID: 16ffb7ba9703
Revises: 98828fc7c366
Create Date: 2026-04-08 23:33:22.779793

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '16ffb7ba9703'
down_revision: Union[str, None] = '98828fc7c366'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TYPE tenant_user_status AS ENUM
        ('invited', 'active', 'suspended', 'deactivated');
    """)
    op.execute("""
        ALTER TABLE tenant_users
            ADD COLUMN status tenant_user_status
            NOT NULL DEFAULT 'active';
    """)
    op.execute("""
        UPDATE tenant_users
            SET status = 'invited'
            WHERE joined_at IS NULL;
    """)
    op.execute("""
        CREATE INDEX ix_tenant_users_status
            ON tenant_users (tenant_id, status);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tenant_users_status;")
    op.execute("ALTER TABLE tenant_users DROP COLUMN status;")
    op.execute("DROP TYPE IF EXISTS tenant_user_status;")