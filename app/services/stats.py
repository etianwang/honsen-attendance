from calendar import monthrange
from datetime import date

from sqlalchemy import func, select, union_all
from sqlalchemy.orm import Session

from app.models import AttendanceEntry, AttendanceValue, Employee, MonthlyRoster, Team, ValueCategory


def month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def quarter_range(year: int, quarter: int) -> tuple[date, date]:
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    return date(year, start_month, 1), date(year, end_month, monthrange(year, end_month)[1])


def half_year_range(year: int, half: int) -> tuple[date, date]:
    start_month, end_month = (1, 6) if half == 1 else (7, 12)
    return date(year, start_month, 1), date(year, end_month, monthrange(year, end_month)[1])


def year_range(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


def _halfday_union_by_range(start_date: date | None = None, end_date: date | None = None):
    """UNION ALL of (employee_id, team_id, value_id), one row per half-day
    slot (AM and PM). Filtered to [start_date, end_date] when given, or
    covers every recorded entry ("since records began") when both are None.
    team_id lives directly on attendance_entries now, so no join to
    monthly_roster is needed to know which team a half-day's credit belongs
    to — that join (and its fan-out risk once a person can be on more than
    one team) is gone entirely."""
    am = select(
        AttendanceEntry.employee_id,
        AttendanceEntry.team_id,
        AttendanceEntry.am_value_id.label("value_id"),
    )
    pm = select(
        AttendanceEntry.employee_id,
        AttendanceEntry.team_id,
        AttendanceEntry.pm_value_id.label("value_id"),
    )
    if start_date is not None:
        entry_date = func.make_date(AttendanceEntry.year, AttendanceEntry.month, AttendanceEntry.day)
        am = am.where(entry_date >= start_date, entry_date <= end_date)
        pm = pm.where(entry_date >= start_date, entry_date <= end_date)
    return union_all(am, pm).subquery()


def _collapse_entries_across_teams(entries: list[AttendanceEntry], values_by_id: dict[int, AttendanceValue]) -> dict:
    """Group entries by (employee_id, year, month, day) and merge every
    team's am/pm values for that slot into one list each — the shared first
    step behind both bulk_month_breakdown() and person_range_category_summary().
    An employee can have MORE THAN ONE attendance_entries row per day (one
    per team they're on, 身兼数职); this collapse is what lets a caller ask
    "did ANY team say he worked this half" without summing/double-counting
    raw per-team rows."""
    per_slot: dict[tuple[int, int, int, int], dict] = {}
    for e in entries:
        key = (e.employee_id, e.year, e.month, e.day)
        slot = per_slot.setdefault(key, {"am": [], "pm": [], "ot": False})
        if e.am_value_id is not None:
            slot["am"].append(values_by_id[e.am_value_id])
        if e.pm_value_id is not None:
            slot["pm"].append(values_by_id[e.pm_value_id])
        if e.evening_overtime:
            slot["ot"] = True
    return per_slot


def bulk_month_breakdown(db: Session, employee_ids: list[int], year: int, month: int) -> dict[int, dict]:
    """Per-employee stats for one month: half-days broken down by tag (code),
    overtime days, and the pooled excess-over-quota number.

    The monthly rest quota is a fact about the PERSON, not about any one
    team, so it must not be computed by summing raw per-team half-days (that
    would double-count a half-day recorded by two teams, or wrongly count a
    half as "rest" just because ONE team had nothing for him that half while
    another team had him working). Instead: collapse every entry across all
    of a person's teams down to one verdict per (day, half) first — if ANY
    team's entry for that half is a worksite value, the half counts as
    worked, full stop; only if EVERY entry for that half is a non-work value
    does it count toward the personal rest/leave/excess tally. Site×team
    credit (which team gets to claim which half-day at which site) is
    handled completely separately in labor_stats()/person_site_team_stats(),
    which deliberately do NOT collapse — each team's own row is its own
    credit there."""
    if not employee_ids:
        return {}

    entries = db.scalars(
        select(AttendanceEntry).where(
            AttendanceEntry.employee_id.in_(employee_ids),
            AttendanceEntry.year == year,
            AttendanceEntry.month == month,
        )
    ).all()
    values_by_id = {v.id: v for v in db.query(AttendanceValue).all()}
    per_slot = _collapse_entries_across_teams(entries, values_by_id)

    per_employee: dict[int, dict] = {
        eid: {"by_code_days": {}, "overtime_days": 0.0, "_nonwork_halfdays": 0.0} for eid in employee_ids
    }

    for (eid, _y, _m, _day), slot in per_slot.items():
        for half in ("am", "pm"):
            vals = slot[half]
            if not vals:
                continue
            if any(v.category == ValueCategory.worksite for v in vals):
                continue  # some team says he worked this half -> not a rest half, regardless of other teams
            tag = vals[0]  # every entry for this half is non-work; rare cross-team disagreement on WHY just takes the first
            by_code = per_employee[eid]["by_code_days"]
            by_code[tag.code] = by_code.get(tag.code, 0.0) + 0.5
            per_employee[eid]["_nonwork_halfdays"] += 1
        if slot["ot"]:
            per_employee[eid]["overtime_days"] += 0.5

    for _eid, data in per_employee.items():
        nonwork_halfdays = data.pop("_nonwork_halfdays")
        # 1 day (= 2 half-days) monthly quota, pooled across every non-work tag and every team.
        data["excess_over_quota_days"] = max(nonwork_halfdays / 2 - 1, 0.0)
    return per_employee


def person_range_category_summary(db: Session, start_date: date | None = None, end_date: date | None = None) -> list[dict]:
    """Per-employee category-day breakdown (请假/病假/休息/... days + overtime
    days) over an arbitrary date range, plus excess-over-quota days for that
    range. The monthly 1-day rest quota does NOT carry over between months —
    each calendar month is settled independently (a month with 2 rest days
    is 1 day over quota even if neighboring months used none of their quota),
    so excess here is the SUM of each covered month's own excess, not one
    pooled quota for the whole range. Uses the same cross-team collapse as
    bulk_month_breakdown(), generalized from one fixed month to any range."""
    entry_date = func.make_date(AttendanceEntry.year, AttendanceEntry.month, AttendanceEntry.day)
    stmt = select(AttendanceEntry)
    if start_date is not None:
        stmt = stmt.where(entry_date >= start_date, entry_date <= end_date)
    entries = db.scalars(stmt).all()
    if not entries:
        return []

    values_by_id = {v.id: v for v in db.query(AttendanceValue).all()}
    employees_by_id = {e.id: e.full_name for e in db.query(Employee).all()}
    per_slot = _collapse_entries_across_teams(entries, values_by_id)

    per_employee: dict[int, dict] = {}
    per_emp_month_nonwork_halfdays: dict[tuple[int, int, int], float] = {}

    for (eid, y, m, _day), slot in per_slot.items():
        data = per_employee.setdefault(eid, {"by_code_days": {}, "overtime_days": 0.0})
        for half in ("am", "pm"):
            vals = slot[half]
            if not vals:
                continue
            if any(v.category == ValueCategory.worksite for v in vals):
                continue
            tag = vals[0]
            by_code = data["by_code_days"]
            by_code[tag.code] = by_code.get(tag.code, 0.0) + 0.5
            month_key = (eid, y, m)
            per_emp_month_nonwork_halfdays[month_key] = per_emp_month_nonwork_halfdays.get(month_key, 0.0) + 1
        if slot["ot"]:
            data["overtime_days"] += 0.5

    for eid, data in per_employee.items():
        data["excess_over_quota_days"] = 0.0
    for (eid, _y, _m), halfdays in per_emp_month_nonwork_halfdays.items():
        per_employee[eid]["excess_over_quota_days"] += max(halfdays / 2 - 1, 0.0)

    return [
        {"employee_id": eid, "name": employees_by_id.get(eid, "?"), **data}
        for eid, data in sorted(per_employee.items(), key=lambda kv: employees_by_id.get(kv[0], ""))
    ]


def team_employee_worksite_days(
    db: Session, team_id: int, employee_ids: list[int], year: int, month: int
) -> dict[int, dict[str, float]]:
    """Per-employee worksite-site day tallies from ONE specific team's own
    attendance_entries rows this month — used by that team's Excel export
    for the "XX工地天数" columns. Deliberately NOT collapsed across teams: a
    dual-team person's other team's entries are irrelevant here, this is
    only what THIS team itself recorded (same non-collapsing reasoning as
    labor_stats()/person_site_team_stats())."""
    if not employee_ids:
        return {}
    halfdays = _halfday_union_by_range(*month_range(year, month))
    stmt = (
        select(halfdays.c.employee_id, AttendanceValue.code, func.count().label("cnt"))
        .select_from(halfdays)
        .join(AttendanceValue, AttendanceValue.id == halfdays.c.value_id)
        .where(
            halfdays.c.team_id == team_id,
            halfdays.c.employee_id.in_(employee_ids),
            AttendanceValue.category == ValueCategory.worksite,
        )
        .group_by(halfdays.c.employee_id, AttendanceValue.code)
    )
    rows = db.execute(stmt).all()
    result: dict[int, dict[str, float]] = {eid: {} for eid in employee_ids}
    for eid, code, cnt in rows:
        result[eid][code] = cnt / 2
    return result


def team_month_stats(db: Session, roster: list[MonthlyRoster], year: int, month: int) -> list[dict]:
    employee_ids = [r.employee_id for r in roster]
    breakdown = bulk_month_breakdown(db, employee_ids, year, month)
    results = []
    for r in roster:
        stats = breakdown.get(r.employee_id, {"by_code_days": {}, "overtime_days": 0.0, "excess_over_quota_days": 0.0})
        results.append({"employee_id": r.employee_id, "name": r.employee.full_name, **stats})
    return results


def labor_stats(db: Session, start_date: date | None = None, end_date: date | None = None) -> list[dict]:
    """Cross-tab of man-days per (worksite value, team) — for a given date
    range (month/quarter/half-year/year/custom), or cumulative since records
    began when both are None. Used for project labor cost estimation. Each
    team's own attendance_entries rows are its own credit — deliberately not
    collapsed across teams the way bulk_month_breakdown() is, since a person
    working for two teams the same half-day (impossible — one entry per team
    per half) or two different halves for two teams should show up as real
    credit for each team."""
    halfdays = _halfday_union_by_range(start_date, end_date)
    stmt = (
        select(
            AttendanceValue.code.label("site"),
            Team.name.label("team"),
            func.count().label("halfdays"),
        )
        .select_from(halfdays)
        .join(AttendanceValue, AttendanceValue.id == halfdays.c.value_id)
        .join(Team, Team.id == halfdays.c.team_id)
        .where(AttendanceValue.category == ValueCategory.worksite)
        .group_by(AttendanceValue.code, Team.name)
    )
    rows = db.execute(stmt).all()
    return [{"site": site, "team": team, "man_days": cnt / 2} for site, team, cnt in rows]


def person_site_team_stats(db: Session, start_date: date | None = None, end_date: date | None = None) -> list[dict]:
    """Same idea as labor_stats() but keeps the employee dimension too — one
    row per (employee, team, site) with man-days, for the "按人员统计" report.
    Not collapsed across teams, same reasoning as labor_stats()."""
    halfdays = _halfday_union_by_range(start_date, end_date)
    stmt = (
        select(
            Employee.id.label("employee_id"),
            Employee.full_name.label("name"),
            Team.name.label("team"),
            AttendanceValue.code.label("site"),
            func.count().label("halfdays"),
        )
        .select_from(halfdays)
        .join(AttendanceValue, AttendanceValue.id == halfdays.c.value_id)
        .join(Team, Team.id == halfdays.c.team_id)
        .join(Employee, Employee.id == halfdays.c.employee_id)
        .where(AttendanceValue.category == ValueCategory.worksite)
        .group_by(Employee.id, Employee.full_name, Team.name, AttendanceValue.code)
        .order_by(Employee.full_name, Team.name, AttendanceValue.code)
    )
    rows = db.execute(stmt).all()
    return [
        {"employee_id": eid, "name": name, "team": team, "site": site, "man_days": cnt / 2}
        for eid, name, team, site, cnt in rows
    ]


def pivot_labor_stats(rows: list[dict]) -> dict:
    sites = sorted({r["site"] for r in rows})
    teams = sorted({r["team"] for r in rows})
    grid = {site: {team: 0.0 for team in teams} for site in sites}
    for r in rows:
        grid[r["site"]][r["team"]] = r["man_days"]
    return {"sites": sites, "teams": teams, "grid": grid}
