"""employee full_name unique

Revision ID: 7160ac23bcde
Revises: 825ea41cb49e
Create Date: 2026-08-06 08:57:38.155626

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7160ac23bcde'
down_revision: Union[str, None] = '825ea41cb49e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint('uq_employee_full_name', 'employees', ['full_name'])


def downgrade() -> None:
    op.drop_constraint('uq_employee_full_name', 'employees', type_='unique')
