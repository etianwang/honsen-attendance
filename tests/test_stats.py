from datetime import date

from app.models import AttendanceEntry, AttendanceValue, Employee, MonthlyRoster, Team, User, UserRole, ValueCategory
from app.services.stats import (
    bulk_month_breakdown,
    labor_stats,
    person_range_category_summary,
    person_site_team_stats,
    team_employee_worksite_days,
)


def _setup_basic(db):
    team = Team(name="水电")
    db.add(team)
    db.flush()

    employee = Employee(full_name="张三")
    db.add(employee)
    db.flush()

    db.add(MonthlyRoster(employee_id=employee.id, team_id=team.id, year=2026, month=8))

    editor = User(username="tester", password_hash="x", display_name="Tester", role=UserRole.admin)
    db.add(editor)
    db.flush()

    worksite = AttendanceValue(code="办公楼施工", category=ValueCategory.worksite, sort_order=0)
    rest = AttendanceValue(code="休息", category=ValueCategory.nonwork, sort_order=0)
    leave = AttendanceValue(code="请假", category=ValueCategory.nonwork, sort_order=1)
    db.add_all([worksite, rest, leave])
    db.flush()

    db.commit()
    return team, employee, editor, worksite, rest, leave


def test_pooled_quota_and_excess(db):
    team, employee, editor, worksite, rest, leave = _setup_basic(db)

    # day1: half a day of rest (0.5 nonwork halfday)
    db.add(
        AttendanceEntry(
            employee_id=employee.id, team_id=team.id, year=2026, month=8, day=1,
            am_value_id=worksite.id, pm_value_id=rest.id, edited_by=editor.id,
        )
    )
    # day2: full day of leave (2 nonwork halfdays = 1 day)
    db.add(
        AttendanceEntry(
            employee_id=employee.id, team_id=team.id, year=2026, month=8, day=2,
            am_value_id=leave.id, pm_value_id=leave.id, edited_by=editor.id,
        )
    )
    # day3: full worksite day, with evening overtime
    db.add(
        AttendanceEntry(
            employee_id=employee.id, team_id=team.id, year=2026, month=8, day=3,
            am_value_id=worksite.id, pm_value_id=worksite.id, evening_overtime=True, edited_by=editor.id,
        )
    )
    db.commit()

    result = bulk_month_breakdown(db, [employee.id], 2026, 8)[employee.id]

    # nonwork total = 0.5 (day1 pm) + 1.0 (day2 full) = 1.5 days; quota is 1 day -> excess 0.5
    assert result["excess_over_quota_days"] == 0.5
    assert result["overtime_days"] == 0.5
    # by_code_days is personal-quota-scoped: only nonwork tags, never worksite
    # codes (those are a per-team credit, see team_employee_worksite_days).
    assert "办公楼施工" not in result["by_code_days"]
    assert result["by_code_days"]["休息"] == 0.5
    assert result["by_code_days"]["请假"] == 1.0

    # worksite day tally is a separate, team-scoped query
    site_days = team_employee_worksite_days(db, team.id, [employee.id], 2026, 8)
    assert site_days[employee.id]["办公楼施工"] == 1.5


def test_no_excess_within_quota(db):
    team, employee, editor, worksite, rest, leave = _setup_basic(db)

    # exactly one half-day of rest -> 0.5 days nonwork, well under the 1-day quota
    db.add(
        AttendanceEntry(
            employee_id=employee.id, team_id=team.id, year=2026, month=8, day=1,
            am_value_id=worksite.id, pm_value_id=rest.id, edited_by=editor.id,
        )
    )
    db.commit()

    result = bulk_month_breakdown(db, [employee.id], 2026, 8)[employee.id]
    assert result["excess_over_quota_days"] == 0.0
    assert result["overtime_days"] == 0.0


def test_person_range_category_summary_quota_does_not_carry_across_months(db):
    """客户明确要求：跨月查询时配额不能累加/不能跨月抵消——8月休息超了1天，
    9月完全没休息，两月合计的超出天数必须还是1天，不能因为9月没用配额就把
    8月的超出"抵消"掉（那样会变成按池化配额算出0天超出，是错的）。"""
    team, employee, editor, worksite, rest, leave = _setup_basic(db)
    db.add(MonthlyRoster(employee_id=employee.id, team_id=team.id, year=2026, month=9))
    db.commit()

    # August: 2 full days of rest = 2 days nonwork, quota is 1 day/month -> 1 day excess in August alone
    db.add_all([
        AttendanceEntry(employee_id=employee.id, team_id=team.id, year=2026, month=8, day=1,
                        am_value_id=rest.id, pm_value_id=rest.id, edited_by=editor.id),
        AttendanceEntry(employee_id=employee.id, team_id=team.id, year=2026, month=8, day=2,
                        am_value_id=rest.id, pm_value_id=rest.id, edited_by=editor.id),
    ])
    # September: full worksite month, no rest at all -> 0 excess in September
    db.add(
        AttendanceEntry(employee_id=employee.id, team_id=team.id, year=2026, month=9, day=1,
                        am_value_id=worksite.id, pm_value_id=worksite.id, edited_by=editor.id)
    )
    db.commit()

    rows = person_range_category_summary(db, date(2026, 8, 1), date(2026, 9, 30))
    result = next(r for r in rows if r["employee_id"] == employee.id)

    # Sum-of-per-month-excess = 1 (August) + 0 (September) = 1 — NOT max(2 - 2, 0) = 0
    # which is what a single pooled 2-month quota would (incorrectly) give.
    assert result["excess_over_quota_days"] == 1.0
    assert result["by_code_days"]["休息"] == 2.0


def test_multi_team_day_not_doubled_or_halved(db):
    """The exact scenario the client described: 张三 is on both 水电组 and
    暖通组 the same month. On the same day, 水电's row says AM=worksite,
    PM=rest; 暖通's row says AM=worksite, PM=worksite (暖通 had him working
    that afternoon too). Personally he worked the WHOLE day (暖通's PM entry
    proves it) — so this must NOT count as any rest half-day, must NOT be
    1.5 days, and must NOT be 0.5 days. But each team's own site credit
    (labor_stats / person_site_team_stats) must reflect exactly what that
    team recorded, independently."""
    shuidian = Team(name="水电组")
    nuantong = Team(name="暖通组")
    db.add_all([shuidian, nuantong])
    db.flush()

    employee = Employee(full_name="张三")
    db.add(employee)
    db.flush()

    db.add(MonthlyRoster(employee_id=employee.id, team_id=shuidian.id, year=2026, month=8))
    db.add(MonthlyRoster(employee_id=employee.id, team_id=nuantong.id, year=2026, month=8))

    editor = User(username="tester2", password_hash="x", display_name="Tester2", role=UserRole.admin)
    db.add(editor)
    db.flush()

    minrex = AttendanceValue(code="Minrex数据中心", category=ValueCategory.worksite, sort_order=0)
    rest = AttendanceValue(code="休息", category=ValueCategory.nonwork, sort_order=0)
    db.add_all([minrex, rest])
    db.flush()
    db.commit()

    # 水电组: AM work, PM rest
    db.add(
        AttendanceEntry(
            employee_id=employee.id, team_id=shuidian.id, year=2026, month=8, day=4,
            am_value_id=minrex.id, pm_value_id=rest.id, edited_by=editor.id,
        )
    )
    # 暖通组: AM work, PM work
    db.add(
        AttendanceEntry(
            employee_id=employee.id, team_id=nuantong.id, year=2026, month=8, day=4,
            am_value_id=minrex.id, pm_value_id=minrex.id, edited_by=editor.id,
        )
    )
    db.commit()

    # A. Personal quota: this day must contribute ZERO rest half-days (暖通's
    # PM entry proves he worked), not 0.5 and not counted twice.
    personal = bulk_month_breakdown(db, [employee.id], 2026, 8)[employee.id]
    assert personal["excess_over_quota_days"] == 0.0
    assert personal["by_code_days"].get("休息", 0.0) == 0.0

    # B. Site×team credit: 水电组 only gets the morning (0.5 day) at Minrex;
    # 暖通组 gets the full day (1.0). Neither is inflated by the other.
    rows = labor_stats(db, None, None)
    by_team = {r["team"]: r["man_days"] for r in rows if r["site"] == "Minrex数据中心"}
    assert by_team["水电组"] == 0.5
    assert by_team["暖通组"] == 1.0

    # C. Same numbers show up in the per-employee breakdown used by the new
    # "按人员统计" report.
    person_rows = person_site_team_stats(db, None, None)
    by_team_person = {r["team"]: r["man_days"] for r in person_rows if r["employee_id"] == employee.id}
    assert by_team_person["水电组"] == 0.5
    assert by_team_person["暖通组"] == 1.0
