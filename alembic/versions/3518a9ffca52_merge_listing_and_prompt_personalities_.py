"""merge_listing_and_prompt_personalities_heads

Revision ID: 3518a9ffca52
Revises: c9f0a1b2d3e4, e3a9f2b1c4d8
Create Date: 2026-04-11 02:47:11.892232

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3518a9ffca52'
down_revision: Union[str, None] = ('c9f0a1b2d3e4', 'e3a9f2b1c4d8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
