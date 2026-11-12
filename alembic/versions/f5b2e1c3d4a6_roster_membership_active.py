"""Preserve attendance when removing a team member."""
from alembic import op
import sqlalchemy as sa

revision = "f5b2e1c3d4a6"
down_revision = "e4a1d0a2c3b4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("monthly_roster", sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False))


def downgrade():
    op.drop_column("monthly_roster", "is_active")
