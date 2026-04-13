"""add_allow_rental_to_chatbot_configs

Revision ID: 9b13363f1da1
Revises: f1a2b3c4d5e6
Create Date: 2026-04-13 10:32:54.488191

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9b13363f1da1'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'chatbot_configs',
        sa.Column(
            'allow_rental',
            sa.Boolean(),
            server_default=sa.text('FALSE'),
            nullable=False,
            comment='When TRUE, listing search includes rental listings. Defaults to FALSE (sale only).',
        ),
    )


def downgrade() -> None:
    op.drop_column('chatbot_configs', 'allow_rental')
