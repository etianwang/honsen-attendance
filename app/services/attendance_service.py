from datetime import date, timedelta

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.models import AttendanceEntry, AttendanceValue, Employee, EmployeeStatus, MonthlyRoster, ValueCategory

HUIGUO_CODE = "回国"


def days_in_month(year: int, month: int) -> int:
    if month == 12:
        return (date(year + 1, 1, 1) - date(year, 12, 1)).days
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def shift_day(year: int, month: int, day: int, delta_days: int) -> tuple[int, int, int]:
    d = date(year, month, day) + timedelta(days=delta_days)
    return d.year, d.month, d.day


def roster_employee_ids(db: Session, team_id: int, year: int, month: int) -> list[int]:
    return list(
        db.scalars(
            select(MonthlyRoster.employee_id).where(
                MonthlyRoster.team_id == team_id, MonthlyRoster.year == year, MonthlyRoster.month == month
            )
        )
    )


def get_active_values(db: Session) -> list[AttendanceValue]:
    return list(
        db.scalars(
            select(AttendanceValue)
            .where(AttendanceValue.is_active.is_(True))
            .order_by(AttendanceValue.category, AttendanceValue.sort_order, AttendanceValue.id)
        )
    )


def get_entries_for_day(
    db: Session, pairs: list[tuple[int, int]], year: int, month: int, day: int
) -> dict[tuple[int, int], AttendanceEntry]:
    """pairs is a list of (employee_id, team_id). One row per employee PER
    TEAM now, so the key is the (employee_id, team_id) pair, not employee_id
    alone — the same function serves a single-team page (all pairs share one
    team_id) and the admin "全体" page (pairs span many teams) identically."""
    if not pairs:
        return {}
    rows = db.scalars(
        select(AttendanceEntry).where(
            tuple_(AttendanceEntry.employee_id, AttendanceEntry.team_id).in_(pairs),
            AttendanceEntry.year == year,
            AttendanceEntry.month == month,
            AttendanceEntry.day == day,
        )
    ).all()
    return {(row.employee_id, row.team_id): row for row in rows}


def get_month_entries(
    db: Session, pairs: list[tuple[int, int]], year: int, month: int
) -> dict[tuple[int, int], dict[int, AttendanceEntry]]:
    """One query for the whole month, grouped by (employee_id, team_id) then
    day — used by the month grid preview and the Excel export instead of a
    query per day."""
    result: dict[tuple[int, int], dict[int, AttendanceEntry]] = {pair: {} for pair in pairs}
    if not pairs:
        return result
    rows = db.scalars(
        select(AttendanceEntry).where(
            tuple_(AttendanceEntry.employee_id, AttendanceEntry.team_id).in_(pairs),
            AttendanceEntry.year == year,
            AttendanceEntry.month == month,
        )
    ).all()
    for row in rows:
        result[(row.employee_id, row.team_id)][row.day] = row
    return result


def get_left_yesterday_employee_ids(
    db: Session, pairs: list[tuple[int, int]], year: int, month: int, day: int
) -> set[tuple[int, int]]:
    """(employee_id, team_id) pairs whose *previous* day was marked 回国 for
    THAT team — used only to default them OFF the "select all" checkbox on
    the next day's entry page. Not a hard removal, and scoped per team: if
    水电 marked someone 回国 yesterday, only 水电's page defaults him off —
    暖通's page is unaffected unless 暖通 independently also marked him 回国."""
    if not pairs:
        return set()
    huiguo = db.scalar(select(AttendanceValue).where(AttendanceValue.code == HUIGUO_CODE))
    if huiguo is None:
        return set()
    py, pm, pd = shift_day(year, month, day, -1)
    rows = db.scalars(
        select(AttendanceEntry).where(
            tuple_(AttendanceEntry.employee_id, AttendanceEntry.team_id).in_(pairs),
            AttendanceEntry.year == py,
            AttendanceEntry.month == pm,
            AttendanceEntry.day == pd,
        )
    ).all()
    return {
        (row.employee_id, row.team_id)
        for row in rows
        if row.am_value_id == huiguo.id or row.pm_value_id == huiguo.id
    }


def get_or_create_entry(
    db: Session, employee_id: int, team_id: int, year: int, month: int, day: int, edited_by: int
) -> AttendanceEntry:
    entry = db.scalar(
        select(AttendanceEntry).where(
            AttendanceEntry.employee_id == employee_id,
            AttendanceEntry.team_id == team_id,
            AttendanceEntry.year == year,
            AttendanceEntry.month == month,
            AttendanceEntry.day == day,
        )
    )
    if entry is None:
        entry = AttendanceEntry(
            employee_id=employee_id, team_id=team_id, year=year, month=month, day=day, edited_by=edited_by
        )
        db.add(entry)
    return entry


def get_huiguo_value_id(db: Session) -> int | None:
    huiguo = db.scalar(select(AttendanceValue).where(AttendanceValue.code == HUIGUO_CODE))
    return huiguo.id if huiguo else None


def sync_employee_status_from_entry(db: Session, entry: AttendanceEntry, huiguo_value_id: int | None) -> None:
    """Whenever an entry's AM or PM value is set to 回国, flip the employee's
    status to returned so they stop showing up as a "在场" roster-add
    candidate. One-directional only — moving status back to 在场/停工 is a
    manual edit on the employee profile, not automatic, so backfilling old
    entries can never silently undo someone's just-returned status."""
    if huiguo_value_id is None:
        return
    if entry.am_value_id != huiguo_value_id and entry.pm_value_id != huiguo_value_id:
        return
    employee = db.get(Employee, entry.employee_id)
    if employee is not None and employee.status != EmployeeStatus.returned:
        employee.status = EmployeeStatus.returned


def is_entry_complete(entry: AttendanceEntry | None) -> bool:
    return entry is not None and entry.am_value_id is not None and entry.pm_value_id is not None


def compose_display(am_code: str | None, pm_code: str | None, ot: bool) -> str:
    if not am_code and not pm_code:
        base = ""
    elif am_code == pm_code:
        base = am_code
    else:
        base = "-".join(part for part in (am_code, pm_code) if part)
    if ot and base:
        base += "-加班"
    elif ot:
        base = "加班"
    return base
