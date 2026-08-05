import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin
from app.database import get_db
from app.models import AttendanceValue, MonthlyRoster, User
from app.services.attendance_service import (
    compose_display,
    days_in_month,
    get_active_values,
    get_entries_for_day,
    get_huiguo_value_id,
    get_left_yesterday_employee_ids,
    get_month_entries,
    get_or_create_entry,
    is_entry_complete,
    shift_day,
    sync_employee_status_from_entry,
)
from app.services.idempotency import claim_idempotency_key
from app.services.roster_service import get_all_teams_roster
from app.templates_env import templates

router = APIRouter(prefix="/admin/attendance", dependencies=[Depends(require_admin)])


class Target(BaseModel):
    employee_id: int
    team_id: int


class BulkApplyRequest(BaseModel):
    idempotency_key: uuid.UUID
    # A person can appear on this page once per team they're on (身兼数职), so
    # a target must name which team's row it's applying to, not just who.
    targets: list[Target]
    scope: str  # "full" | "am" | "pm" | "ot"
    value_id: int | None = None
    note: str | None = None
    ot_value: bool = True


class IndividualEditRequest(BaseModel):
    idempotency_key: uuid.UUID
    am_value_id: int | None = None
    am_note: str | None = None
    pm_value_id: int | None = None
    pm_note: str | None = None
    evening_overtime: bool | None = None


def _all_teams_pairs(db: Session, year: int, month: int) -> set[tuple[int, int]]:
    return set(
        db.execute(
            select(MonthlyRoster.employee_id, MonthlyRoster.team_id).where(
                MonthlyRoster.year == year, MonthlyRoster.month == month
            )
        ).all()
    )


@router.get("")
def admin_attendance_today(user: User = Depends(require_admin)):
    today = date.today()
    return RedirectResponse(url=f"/admin/attendance/{today.year}/{today.month}/{today.day}", status_code=303)


@router.get("/{year}/{month}/{day}")
def admin_attendance_day_page(
    request: Request,
    year: int,
    month: int,
    day: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    roster = get_all_teams_roster(db, year, month)
    pairs = [(r.employee_id, r.team_id) for r in roster]
    entries = get_entries_for_day(db, pairs, year, month, day)
    excluded_default = get_left_yesterday_employee_ids(db, pairs, year, month, day)
    values = get_active_values(db)

    employees = []
    for r in roster:
        e = entries.get((r.employee_id, r.team_id))
        employees.append(
            {
                "id": r.employee_id,
                "team_id": r.team_id,  # presence of this field is what puts attendance_day.js into composite mode
                "name": r.employee.full_name,
                "team_name": r.team.name,
                "am_value_id": e.am_value_id if e else None,
                "am_note": e.am_note if e else None,
                "pm_value_id": e.pm_value_id if e else None,
                "pm_note": e.pm_note if e else None,
                "evening_overtime": e.evening_overtime if e else False,
                "complete": is_entry_complete(e),
                "default_excluded": (r.employee_id, r.team_id) in excluded_default,
            }
        )

    values_json = [
        {"id": v.id, "code": v.code, "category": v.category.value, "requires_note": v.requires_note}
        for v in values
    ]

    py, pmn, pd = shift_day(year, month, day, -1)
    ny, nmn, nd = shift_day(year, month, day, 1)

    return templates.TemplateResponse(
        request,
        "admin/attendance_all_day.html",
        {
            "user": user,
            "active_nav": "admin_attendance",
            "year": year,
            "month": month,
            "day": day,
            "employees": employees,
            "values": values_json,
            "prev": {"year": py, "month": pmn, "day": pd},
            "next": {"year": ny, "month": nmn, "day": nd},
        },
    )


@router.post("/{year}/{month}/{day}/bulk")
def admin_attendance_bulk(
    year: int,
    month: int,
    day: int,
    payload: BulkApplyRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not claim_idempotency_key(db, payload.idempotency_key):
        return {"status": "duplicate_ignored"}

    valid_pairs = _all_teams_pairs(db, year, month)
    targets = [(t.employee_id, t.team_id) for t in payload.targets if (t.employee_id, t.team_id) in valid_pairs]
    if not targets:
        return {"status": "ok", "updated": 0}

    value: AttendanceValue | None = None
    if payload.scope in ("full", "am", "pm"):
        if payload.value_id is None:
            raise HTTPException(400, "缺少要应用的值")
        value = db.get(AttendanceValue, payload.value_id)
        if value is None:
            raise HTTPException(400, "无效的值")
    elif payload.scope != "ot":
        raise HTTPException(400, "未知的范围")

    note = payload.note if (value is not None and value.requires_note) else None
    huiguo_id = get_huiguo_value_id(db)

    updated = 0
    for eid, tid in targets:
        entry = get_or_create_entry(db, eid, tid, year, month, day, user.id)
        if payload.scope == "full":
            entry.am_value_id = value.id
            entry.am_note = note
            entry.pm_value_id = value.id
            entry.pm_note = note
        elif payload.scope == "am":
            entry.am_value_id = value.id
            entry.am_note = note
        elif payload.scope == "pm":
            entry.pm_value_id = value.id
            entry.pm_note = note
        elif payload.scope == "ot":
            entry.evening_overtime = payload.ot_value
        entry.edited_by = user.id
        sync_employee_status_from_entry(db, entry, huiguo_id)
        updated += 1
    db.commit()
    return {"status": "ok", "updated": updated}


@router.post("/{year}/{month}/{day}/{team_id}/{employee_id}")
def admin_attendance_individual(
    year: int,
    month: int,
    day: int,
    team_id: int,
    employee_id: int,
    payload: IndividualEditRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not claim_idempotency_key(db, payload.idempotency_key):
        return {"status": "duplicate_ignored"}

    valid_pairs = _all_teams_pairs(db, year, month)
    if (employee_id, team_id) not in valid_pairs:
        raise HTTPException(status_code=403, detail="该员工不在这个班组当月的花名册中")

    entry = get_or_create_entry(db, employee_id, team_id, year, month, day, user.id)
    provided = payload.model_fields_set - {"idempotency_key"}
    if "am_value_id" in provided:
        entry.am_value_id = payload.am_value_id
    if "am_note" in provided:
        entry.am_note = payload.am_note
    if "pm_value_id" in provided:
        entry.pm_value_id = payload.pm_value_id
    if "pm_note" in provided:
        entry.pm_note = payload.pm_note
    if "evening_overtime" in provided:
        entry.evening_overtime = payload.evening_overtime
    entry.edited_by = user.id
    sync_employee_status_from_entry(db, entry, get_huiguo_value_id(db))
    db.commit()
    return {"status": "ok"}


@router.get("/{year}/{month}")
def admin_attendance_month_grid(
    request: Request,
    year: int,
    month: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    roster = get_all_teams_roster(db, year, month)
    pairs = [(r.employee_id, r.team_id) for r in roster]
    total_days = days_in_month(year, month)
    all_entries = get_month_entries(db, pairs, year, month)
    value_codes = {v.id: v.code for v in db.query(AttendanceValue).all()}

    rows = []
    for r in roster:
        cells = []
        for day in range(1, total_days + 1):
            entry = all_entries[(r.employee_id, r.team_id)].get(day)
            if entry is None:
                cells.append({"day": day, "text": "", "complete": False})
            else:
                am_code = value_codes.get(entry.am_value_id)
                pm_code = value_codes.get(entry.pm_value_id)
                cells.append(
                    {
                        "day": day,
                        "text": compose_display(am_code, pm_code, entry.evening_overtime),
                        "complete": is_entry_complete(entry),
                    }
                )
        rows.append(
            {"employee_id": r.employee_id, "name": r.employee.full_name, "team_name": r.team.name, "cells": cells}
        )

    return templates.TemplateResponse(
        request,
        "admin/attendance_all_month_grid.html",
        {
            "user": user,
            "active_nav": "admin_attendance",
            "year": year,
            "month": month,
            "days": list(range(1, total_days + 1)),
            "rows": rows,
        },
    )
