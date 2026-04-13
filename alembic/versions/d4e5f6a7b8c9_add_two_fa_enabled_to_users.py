"""add_two_fa_enabled_to_users

Revision ID: d4e5f6a7b8c9
Revises: 9b13363f1da1
Branch Labels: None
Depends on: None

Create Date: 2026-04-13 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = '9b13363f1da1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'two_fa_enabled',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('true'),
            comment='When true, login requires an OTP sent to the user\'s email. Enabled for all users by default.',
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'two_fa_enabled')
