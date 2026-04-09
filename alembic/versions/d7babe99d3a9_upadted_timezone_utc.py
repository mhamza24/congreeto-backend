"""upadted timezone :utc

Revision ID: d7babe99d3a9
Revises: 0fba5609e180
Create Date: 2026-04-08 22:36:53.179960

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7babe99d3a9'
down_revision: Union[str, None] = '0fba5609e180'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_users_public_id', table_name='users')
    op.create_index('ix_users_public_id', 'users', ['public_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_users_public_id', table_name='users')
    op.create_index('ix_users_public_id', 'users', ['public_id'], unique=True)