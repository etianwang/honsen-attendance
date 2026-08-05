from app.models import Employee, MonthlyRoster, Team
from app.services.roster_service import add_employee_to_roster, copy_forward, get_roster


def test_copy_forward_adds_rows_and_is_idempotent(db):
    team = Team(name="暖通")
    db.add(team)
    db.flush()

    e1 = Employee(full_name="员工甲")
    e2 = Employee(full_name="员工乙")
    db.add_all([e1, e2])
    db.flush()

    db.add(MonthlyRoster(employee_id=e1.id, team_id=team.id, year=2026, month=7))
    db.add(MonthlyRoster(employee_id=e2.id, team_id=team.id, year=2026, month=7))
    db.commit()

    added = copy_forward(db, team.id, 2026, 8)
    assert added == 2
    assert len(get_roster(db, team.id, 2026, 8)) == 2

    # calling it again must not duplicate rows
    added_again = copy_forward(db, team.id, 2026, 8)
    assert added_again == 0
    assert len(get_roster(db, team.id, 2026, 8)) == 2

    # the source month must be untouched
    assert len(get_roster(db, team.id, 2026, 7)) == 2


def test_copy_forward_skips_already_present_employee(db):
    team = Team(name="土建")
    db.add(team)
    db.flush()

    e1 = Employee(full_name="员工丙")
    e2 = Employee(full_name="员工丁")
    db.add_all([e1, e2])
    db.flush()

    db.add(MonthlyRoster(employee_id=e1.id, team_id=team.id, year=2026, month=7))
    db.add(MonthlyRoster(employee_id=e2.id, team_id=team.id, year=2026, month=7))
    # e1 was already manually added to next month before carry-forward runs
    db.add(MonthlyRoster(employee_id=e1.id, team_id=team.id, year=2026, month=8))
    db.commit()

    added = copy_forward(db, team.id, 2026, 8)
    assert added == 1  # only e2 gets added
    assert len(get_roster(db, team.id, 2026, 8)) == 2


def test_add_employee_to_second_team_same_month(db):
    """Regression test: an employee already on one team's roster this month
    must still be addable to a DIFFERENT team's roster the same month
    (身兼数职) — add_employee_to_roster's "already exists" check must be
    scoped by team_id, not just employee_id+year+month, or this silently
    no-ops and the person never actually gets added to the second team."""
    team_a = Team(name="水电组测试")
    team_b = Team(name="暖通组测试")
    db.add_all([team_a, team_b])
    db.flush()

    employee = Employee(full_name="员工戊")
    db.add(employee)
    db.flush()
    db.commit()

    row_a = add_employee_to_roster(db, team_a.id, 2026, 8, employee_id=employee.id)
    row_b = add_employee_to_roster(db, team_b.id, 2026, 8, employee_id=employee.id)

    assert row_a.team_id == team_a.id
    assert row_b.team_id == team_b.id
    assert len(get_roster(db, team_a.id, 2026, 8)) == 1
    assert len(get_roster(db, team_b.id, 2026, 8)) == 1
