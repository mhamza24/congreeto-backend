"""fix_billing_utc_defaults

Revision ID: 9da2f8916832
Revises: 52c7af1fddad
Create Date: 2026-04-09 13:45:46.589659

"""
from typing import Sequence, Union
from alembic import op

revision: str = '<keep generated>'
down_revision: Union[str, None] = '52c7af1fddad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES_BOTH = [
    "addons",
    "plans",
    "tenant_subscriptions",
    "tenant_addon_subscriptions",
]

TABLES_RECORDED_AT = [
    "usage_records",
]


def upgrade() -> None:
    for table in TABLES_BOTH:
        op.execute(f"""
            ALTER TABLE {table}
                ALTER COLUMN created_at SET DEFAULT (NOW() AT TIME ZONE 'UTC'),
                ALTER COLUMN updated_at SET DEFAULT (NOW() AT TIME ZONE 'UTC');
        """)

    for table in TABLES_RECORDED_AT:
        op.execute(f"""
            ALTER TABLE {table}
                ALTER COLUMN recorded_at SET DEFAULT (NOW() AT TIME ZONE 'UTC');
        """)


def downgrade() -> None:
    for table in TABLES_BOTH:
        op.execute(f"""
            ALTER TABLE {table}
                ALTER COLUMN created_at SET DEFAULT NOW(),
                ALTER COLUMN updated_at SET DEFAULT NOW();
        """)

    for table in TABLES_RECORDED_AT:
        op.execute(f"""
            ALTER TABLE {table}
                ALTER COLUMN recorded_at SET DEFAULT NOW();
        """)