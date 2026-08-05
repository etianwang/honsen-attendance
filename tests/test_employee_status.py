from app.models import AttendanceEntry, AttendanceValue, Employee, EmployeeStatus, MonthlyRoster, Team, User, UserRole, ValueCategory
from app.services.attendance_service import get_huiguo_value_id, sync_employee_status_from_entry
from app.services.roster_service import add_employees_bulk, list_present_candidates


def test_list_present_candidates_excludes_current_team_but_not_other_teams(db):
    team_a = Team(name="水电组")
    team_b = Team(name="暖通组")
    db.add_all([team_a, team_b])
    db.flush()

    on_a_already = Employee(full_name="甲")
    only_active_elsewhere = Employee(full_name="乙")
    returned_employee = Employee(full_name="丙", status=EmployeeStatus.returned)
    db.add_all([on_a_already, only_active_elsewhere, returned_employee])
    db.flush()

    db.add(MonthlyRoster(employee_id=on_a_already.id, team_id=team_a.id, year=2026, month=8))
    db.commit()

    candidates_a = {e.id for e in list_present_candidates(db, team_a.id, 2026, 8)}
    candidates_b = {e.id for e in list_present_candidates(db, team_b.id, 2026, 8)}

    assert on_a_already.id not in candidates_a  # already on team A's roster this month
    assert on_a_already.id in candidates_b  # 身兼数职 — still a valid candidate for team B
    assert only_active_elsewhere.id in candidates_a
    assert returned_employee.id not in candidates_a  # not "在场"


def test_add_employees_bulk_adds_multiple_and_ignores_invalid_ids(db):
    team = Team(name="土建组")
    db.add(team)
    db.flush()

    e1 = Employee(full_name="丁")
    e2 = Employee(full_name="戊")
    returned_employee = Employee(full_name="己", status=EmployeeStatus.returned)
    db.add_all([e1, e2, returned_employee])
    db.flush()
    db.commit()

    added = add_employees_bulk(db, team.id, 2026, 8, [e1.id, e2.id, returned_employee.id, 999999])
    assert added == 2  # returned employee and nonexistent id are silently skipped

    roster_employee_ids = {r.employee_id for r in db.query(MonthlyRoster).filter_by(team_id=team.id).all()}
    assert roster_employee_ids == {e1.id, e2.id}

    # calling again with the same ids must not duplicate rows
    added_again = add_employees_bulk(db, team.id, 2026, 8, [e1.id, e2.id])
    assert added_again == 0


def test_huiguo_value_sync_flips_employee_status(db):
    team = Team(name="测试组")
    db.add(team)
    db.flush()

    employee = Employee(full_name="庚")
    editor = User(username="tester2", password_hash="x", display_name="Tester2", role=UserRole.admin)
    huiguo = AttendanceValue(code="回国", category=ValueCategory.worksite, sort_order=0)
    other = AttendanceValue(code="办公楼施工", category=ValueCategory.worksite, sort_order=1)
    db.add_all([employee, editor, huiguo, other])
    db.flush()
    db.commit()

    db.add(MonthlyRoster(employee_id=employee.id, team_id=team.id, year=2026, month=8))
    db.commit()

    huiguo_id = get_huiguo_value_id(db)
    assert huiguo_id == huiguo.id

    entry = AttendanceEntry(
        employee_id=employee.id, team_id=team.id, year=2026, month=8, day=1,
        am_value_id=other.id, pm_value_id=huiguo.id, edited_by=editor.id,
    )
    db.add(entry)
    db.flush()

    sync_employee_status_from_entry(db, entry, huiguo_id)
    db.commit()

    assert employee.status == EmployeeStatus.returned

    # calling again is a no-op, not an error
    sync_employee_status_from_entry(db, entry, huiguo_id)
    db.commit()
    assert employee.status == EmployeeStatus.returned


def test_sync_ignores_entries_without_huiguo_value(db):
    team = Team(name="测试组2")
    db.add(team)
    db.flush()

    employee = Employee(full_name="辛")
    editor = User(username="tester3", password_hash="x", display_name="Tester3", role=UserRole.admin)
    other = AttendanceValue(code="办公楼施工2", category=ValueCategory.worksite, sort_order=0)
    db.add_all([employee, editor, other])
    db.flush()
    db.add(MonthlyRoster(employee_id=employee.id, team_id=team.id, year=2026, month=8))
    db.commit()

    entry = AttendanceEntry(
        employee_id=employee.id, team_id=team.id, year=2026, month=8, day=1,
        am_value_id=other.id, pm_value_id=other.id, edited_by=editor.id,
    )
    db.add(entry)
    db.flush()

    huiguo_id = get_huiguo_value_id(db)  # None — no 回国 value configured in this test's data
    sync_employee_status_from_entry(db, entry, huiguo_id)
    db.commit()

    assert employee.status == EmployeeStatus.active
