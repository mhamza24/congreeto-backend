from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = '98828fc7c366'
down_revision: Union[str, None] = 'd7babe99d3a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Get all tables that have created_at
    tables_with_created_at = conn.execute(text("""
        SELECT table_name FROM information_schema.columns
        WHERE column_name = 'created_at' AND table_schema = 'public'
    """)).fetchall()

    # Get all tables that have updated_at
    tables_with_updated_at = conn.execute(text("""
        SELECT table_name FROM information_schema.columns
        WHERE column_name = 'updated_at' AND table_schema = 'public'
    """)).fetchall()

    updated_at_tables = {row[0] for row in tables_with_updated_at}

    for (table,) in tables_with_created_at:
        if table in updated_at_tables:
            op.execute(f"""
                ALTER TABLE {table}
                    ALTER COLUMN created_at SET DEFAULT (NOW() AT TIME ZONE 'UTC'),
                    ALTER COLUMN updated_at SET DEFAULT (NOW() AT TIME ZONE 'UTC');
            """)
        else:
            op.execute(f"""
                ALTER TABLE {table}
                    ALTER COLUMN created_at SET DEFAULT (NOW() AT TIME ZONE 'UTC');
            """)


def downgrade() -> None:
    conn = op.get_bind()

    tables_with_created_at = conn.execute(text("""
        SELECT table_name FROM information_schema.columns
        WHERE column_name = 'created_at' AND table_schema = 'public'
    """)).fetchall()

    tables_with_updated_at = conn.execute(text("""
        SELECT table_name FROM information_schema.columns
        WHERE column_name = 'updated_at' AND table_schema = 'public'
    """)).fetchall()

    updated_at_tables = {row[0] for row in tables_with_updated_at}

    for (table,) in tables_with_created_at:
        if table in updated_at_tables:
            op.execute(f"""
                ALTER TABLE {table}
                    ALTER COLUMN created_at SET DEFAULT NOW(),
                    ALTER COLUMN updated_at SET DEFAULT NOW();
            """)
        else:
            op.execute(f"""
                ALTER TABLE {table}
                    ALTER COLUMN created_at SET DEFAULT NOW();
            """)