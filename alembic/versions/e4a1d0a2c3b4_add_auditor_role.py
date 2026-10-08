"""add auditor role

Revision ID: e4a1d0a2c3b4
Revises: bfa67264b264
"""

from alembic import op


revision = "e4a1d0a2c3b4"
down_revision = "bfa67264b264"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'auditor'")
    op.drop_constraint("chk_team_lead_has_team", "users", type_="check")
    op.create_check_constraint(
        "chk_team_lead_has_team",
        "users",
        "(role = 'team_lead' AND team_id IS NOT NULL) OR (role IN ('admin', 'auditor') AND team_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("chk_team_lead_has_team", "users", type_="check")
    op.create_check_constraint(
        "chk_team_lead_has_team", "users", "role = 'admin' OR (role = 'team_lead' AND team_id IS NOT NULL)"
    )
