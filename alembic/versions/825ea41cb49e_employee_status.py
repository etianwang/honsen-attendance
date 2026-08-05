"""employee status

Revision ID: 825ea41cb49e
Revises: b9bf00cb9f68
Create Date: 2026-08-05 08:38:32.495623

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '825ea41cb49e'
down_revision: Union[str, None] = 'b9bf00cb9f68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


employee_status_enum = sa.Enum('active', 'returned', 'suspended', name='employee_status')


def upgrade() -> None:
    employee_status_enum.create(op.get_bind(), checkfirst=True)
    op.add_column('employees', sa.Column('status', employee_status_enum, server_default='active', nullable=False))


def downgrade() -> None:
    op.drop_column('employees', 'status')
    employee_status_enum.drop(op.get_bind(), checkfirst=True)
