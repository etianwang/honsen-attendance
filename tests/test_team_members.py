import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models import AttendanceEntry, Employee, Team, User, UserRole
from app.services.roster_service import (
    add_employee_to_roster, all_employees_with_current_teams, copy_forward,
    get_roster, list_present_candidates, remove_employee_from_roster,
)


def test_remove_preserves_history_and_other_memberships(db):
    team, other = Team(name="旧班组", is_active=False), Team(name="新班组")
    employee = Employee(full_name="测试成员")
    admin = User(username="admin", password_hash="x", display_name="Admin", role=UserRole.admin)
    db.add_all([team, other, employee, admin])
    db.flush()
    for team_id, month in [(team.id, 10), (team.id, 11), (other.id, 11)]:
        add_employee_to_roster(db, team_id, 2026, month, employee.id)
    entry = AttendanceEntry(employee_id=employee.id, team_id=team.id, year=2026, month=11, day=1, edited_by=admin.id)
    db.add(entry)
    db.commit()
    row_id = get_roster(db, team.id, 2026, 11)[0].id

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        with TestClient(app) as client:
            page = client.get(f"/admin/teams/{team.id}/members?year=2026&month=11")
            assert page.status_code == 200
            assert "测试成员" in page.text and "班组已停用" in page.text
            response = client.post(f"/admin/teams/{team.id}/members/{employee.id}/remove", data={"year": 2026, "month": 11})
            assert response.status_code == 200
            assert "该月暂无成员" in response.text
            assert client.get(f"/admin/teams/{team.id}/members?month=13").status_code == 422
            assert client.get("/admin/teams/999999/members").status_code == 404
    finally:
        app.dependency_overrides.clear()

    from app.routers.attendance_router import _roster_employee_ids
    from app.routers.admin_attendance_router import _all_teams_pairs
    assert employee.id not in _roster_employee_ids(db, team.id, 2026, 11)
    assert (employee.id, team.id) not in _all_teams_pairs(db, 2026, 11)
    assert (employee.id, other.id) in _all_teams_pairs(db, 2026, 11)
    assert db.get(AttendanceEntry, entry.id) is not None
    assert db.get(Employee, employee.id) is not None
    assert get_roster(db, team.id, 2026, 11)[0].id == row_id
    assert not get_roster(db, team.id, 2026, 11, active_only=True)
    assert len(get_roster(db, other.id, 2026, 11, active_only=True)) == 1
    assert len(get_roster(db, team.id, 2026, 10, active_only=True)) == 1
    assert all_employees_with_current_teams(db, 2026, 11)[0][1] == [other.name]
    assert not remove_employee_from_roster(db, team.id, 2026, 11, employee.id)
    assert copy_forward(db, team.id, 2026, 12) == 0
    assert copy_forward(db, team.id, 2026, 11) == 0  # cannot resurrect a removed member
    assert employee in list_present_candidates(db, team.id, 2026, 11)
    assert add_employee_to_roster(db, team.id, 2026, 11, employee.id).id == row_id
    assert len(get_roster(db, team.id, 2026, 11, active_only=True)) == 1


@pytest.mark.parametrize("role", [UserRole.team_lead, UserRole.auditor])
def test_member_management_requires_admin(role):
    user = User(username="test", password_hash="x", display_name="Test", role=role, team_id=1)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with TestClient(app) as client:
            assert client.get("/admin/teams/1/members").status_code == 403
            assert client.post("/admin/teams/1/members/1/remove", data={"year": 2026, "month": 11}).status_code == 403
    finally:
        app.dependency_overrides.clear()
