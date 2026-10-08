import pytest
from fastapi import HTTPException
from unittest.mock import Mock

from app.auth.dependencies import require_employee_edit_scope, require_employee_scope, require_stats_access, require_team_scope
from app.models import Employee, User, UserRole


def test_admin_can_access_any_team():
    admin = User(username="a", password_hash="x", display_name="Admin", role=UserRole.admin, team_id=None)
    result = require_team_scope(team_id=42, user=admin)
    assert result is admin


def test_team_lead_can_access_own_team():
    lead = User(username="b", password_hash="x", display_name="Lead", role=UserRole.team_lead, team_id=3)
    result = require_team_scope(team_id=3, user=lead)
    assert result is lead


def test_team_lead_cannot_access_other_team():
    lead = User(username="c", password_hash="x", display_name="Lead", role=UserRole.team_lead, team_id=3)
    with pytest.raises(HTTPException) as exc_info:
        require_team_scope(team_id=99, user=lead)
    assert exc_info.value.status_code == 403


def test_auditor_can_only_use_statistics_access():
    auditor = User(username="audit", password_hash="x", display_name="Audit", role=UserRole.auditor)
    assert require_stats_access(user=auditor) is auditor
    lead = User(username="lead2", password_hash="x", display_name="Lead", role=UserRole.team_lead, team_id=1)
    with pytest.raises(HTTPException):
        require_stats_access(user=lead)
    with pytest.raises(HTTPException):
        require_team_scope(team_id=1, user=auditor)


def test_auditor_can_view_but_not_edit_employee():
    auditor = User(username="auditor2", password_hash="x", display_name="Audit", role=UserRole.auditor)
    employee = Employee(full_name="Worker")
    db = Mock()
    db.get.return_value = employee
    assert require_employee_scope(employee_id=1, user=auditor, db=db) is employee
    with pytest.raises(HTTPException):
        require_employee_edit_scope(employee_id=1, user=auditor, db=db)
