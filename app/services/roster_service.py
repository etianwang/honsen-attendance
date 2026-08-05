from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Employee, EmployeeStatus, MonthlyRoster, Team


def prev_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def get_roster(db: Session, team_id: int, year: int, month: int) -> list[MonthlyRoster]:
    stmt = (
        select(MonthlyRoster)
        .options(joinedload(MonthlyRoster.employee))
        .join(MonthlyRoster.employee)
        .where(MonthlyRoster.team_id == team_id, MonthlyRoster.year == year, MonthlyRoster.month == month)
        .order_by(Employee.full_name)
    )
    return list(db.scalars(stmt))


def get_all_teams_roster(db: Session, year: int, month: int) -> list[MonthlyRoster]:
    """Same shape as get_roster but across every team — for the admin
    "全体录入" page, so an admin doesn't have to click into each team one by
    one just to enter a normal day."""
    stmt = (
        select(MonthlyRoster)
        .options(joinedload(MonthlyRoster.employee), joinedload(MonthlyRoster.team))
        .join(MonthlyRoster.employee)
        .join(MonthlyRoster.team)
        .where(MonthlyRoster.year == year, MonthlyRoster.month == month)
        .order_by(Team.name, Employee.full_name)
    )
    return list(db.scalars(stmt))


def copy_forward(db: Session, team_id: int, year: int, month: int) -> int:
    """Copy last month's roster forward into (year, month) for this team,
    skipping anyone already present this month. Returns rows added."""
    py, pm = prev_month(year, month)
    prev_rows = db.scalars(
        select(MonthlyRoster).where(
            MonthlyRoster.team_id == team_id, MonthlyRoster.year == py, MonthlyRoster.month == pm
        )
    ).all()
    existing_employee_ids = {
        row.employee_id
        for row in db.scalars(
            select(MonthlyRoster).where(
                MonthlyRoster.team_id == team_id, MonthlyRoster.year == year, MonthlyRoster.month == month
            )
        )
    }
    added = 0
    for row in prev_rows:
        if row.employee_id in existing_employee_ids:
            continue
        db.add(MonthlyRoster(employee_id=row.employee_id, team_id=team_id, year=year, month=month))
        added += 1
    db.commit()
    return added


def list_present_candidates(db: Session, team_id: int, year: int, month: int) -> list[Employee]:
    """Employees with status='在场' who aren't already on THIS team's roster
    for (year, month) — the pool the roster page's "添加组员" picker offers.
    Someone already on a DIFFERENT team's roster this month (身兼数职) still
    shows up here; only membership in this specific team+month is excluded."""
    already_on_roster = set(
        db.scalars(
            select(MonthlyRoster.employee_id).where(
                MonthlyRoster.team_id == team_id, MonthlyRoster.year == year, MonthlyRoster.month == month
            )
        )
    )
    stmt = select(Employee).where(Employee.status == EmployeeStatus.active).order_by(Employee.full_name)
    return [e for e in db.scalars(stmt) if e.id not in already_on_roster]


def all_employees_with_current_teams(
    db: Session, year: int, month: int, q: str | None = None
) -> list[tuple[Employee, list[str]]]:
    """Every employee ever created (not just those on some team's roster
    right now), each paired with whichever team(s) they're on for
    (year, month) — empty list if none. This is the admin "员工管理"
    directory: unlike a team's own 花名册 page, it isn't scoped to one team,
    so it's the only place to find/search someone regardless of which team
    (if any) they're currently on."""
    stmt = select(Employee).order_by(Employee.full_name)
    if q:
        stmt = stmt.where(Employee.full_name.ilike(f"%{q.strip()}%"))
    employees = list(db.scalars(stmt))

    roster_rows = db.scalars(
        select(MonthlyRoster)
        .options(joinedload(MonthlyRoster.team))
        .where(MonthlyRoster.year == year, MonthlyRoster.month == month)
    ).all()
    teams_by_employee: dict[int, list[str]] = {}
    for r in roster_rows:
        teams_by_employee.setdefault(r.employee_id, []).append(r.team.name)

    return [(e, teams_by_employee.get(e.id, [])) for e in employees]


def add_employee_to_roster(db: Session, team_id: int, year: int, month: int, employee_id: int) -> MonthlyRoster:
    # Must also filter by team_id — an employee can be on more than one
    # team's roster in the same month (身兼数职). Without team_id here, adding
    # someone who's already on a DIFFERENT team this month would just find
    # that other team's row and return it, silently failing to add them to
    # this team at all.
    existing = db.scalar(
        select(MonthlyRoster).where(
            MonthlyRoster.employee_id == employee_id,
            MonthlyRoster.team_id == team_id,
            MonthlyRoster.year == year,
            MonthlyRoster.month == month,
        )
    )
    if existing:
        return existing
    row = MonthlyRoster(employee_id=employee_id, team_id=team_id, year=year, month=month)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_employees_bulk(db: Session, team_id: int, year: int, month: int, employee_ids: list[int]) -> int:
    """Add every id in employee_ids to this team's (year, month) roster in
    one go — backs the roster page's pick-then-confirm "预选" flow. Reuses
    add_employee_to_roster's own already-on-this-team check, so calling this
    twice with overlapping ids never creates duplicate rows. employee_ids is
    deduped up front — without it, a repeated id in the same request (e.g. a
    replayed/double-submitted form) would inflate the returned count even
    though add_employee_to_roster itself only ever inserts it once."""
    added = 0
    eligible_ids = {e.id for e in list_present_candidates(db, team_id, year, month)}
    for employee_id in dict.fromkeys(employee_ids):
        if employee_id not in eligible_ids:
            continue
        add_employee_to_roster(db, team_id, year, month, employee_id=employee_id)
        added += 1
    return added


def remove_employee_from_roster(db: Session, team_id: int, year: int, month: int, employee_id: int) -> bool:
    row = db.scalar(
        select(MonthlyRoster).where(
            MonthlyRoster.employee_id == employee_id,
            MonthlyRoster.team_id == team_id,
            MonthlyRoster.year == year,
            MonthlyRoster.month == month,
        )
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True
