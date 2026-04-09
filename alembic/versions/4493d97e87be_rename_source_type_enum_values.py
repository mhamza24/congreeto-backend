"""rename_source_type_enum_values

Revision ID: 4493d97e87be
Revises: fd90108b12bc
Create Date: 2026-04-10 01:34:04.048723

Renames:
    source_type enum: 'pdf' -> 'document', 'text' -> 'manual_qa'

PostgreSQL supports ALTER TYPE ... RENAME VALUE since PG 10.
Safe to run with zero downtime — no table rewrite needed.
"""
from typing import Sequence, Union

from alembic import op


revision: str = '4493d97e87be'
down_revision: Union[str, None] = 'fd90108b12bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE source_type RENAME VALUE 'pdf' TO 'document'")
    op.execute("ALTER TYPE source_type RENAME VALUE 'text' TO 'manual_qa'")


def downgrade() -> None:
    op.execute("ALTER TYPE source_type RENAME VALUE 'document' TO 'pdf'")
    op.execute("ALTER TYPE source_type RENAME VALUE 'manual_qa' TO 'text'")
