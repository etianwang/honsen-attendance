import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import require_team_scope
from app.database import get_db
from app.models import AttendanceValue, Team, User
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
from app.services.daily_photo_service import (
    MAX_DAILY_PHOTOS,
    count_daily_photos,
    delete_daily_photo,
    get_daily_photos,
    get_photo_by_id,
    try_sync_to_drive,
    upload_daily_photo,
)
from app.services.file_storage import resolve_path
from app.services.idempotency import claim_idempotency_key
from app.services.roster_service import get_roster
from app.templates_env import templates

router = APIRouter()


class BulkApplyRequest(BaseModel):
    idempotency_key: uuid.UUID
    employee_ids: list[int]
    scope: str  # "full" | "am" | "pm" | "ot"
    value_id: int | None = None
    note: str | None = None
    ot_value: bool = True  # only used when scope == "ot"


class IndividualEditRequest(BaseModel):
    idempotency_key: uuid.UUID
    am_value_id: int | None = None
    am_note: str | None = None
    pm_value_id: int | None = None
    pm_note: str | None = None
    evening_overtime: bool | None = None


def _roster_employee_ids(db: Session, team_id: int, year: int, month: int) -> set[int]:
    return {r.employee_id for r in get_roster(db, team_id, year, month)}


def _get_scoped_photo(db: Session, team_id: int, year: int, month: int, day: int, photo_id: int):
    """Fetch a photo by id and confirm it actually belongs to this
    team/day — without this a team lead could guess another team's photo_id
    and retry-sync/delete/view it."""
    photo = get_photo_by_id(db, photo_id)
    if photo is None or (photo.team_id, photo.year, photo.month, photo.day) != (team_id, year, month, day):
        raise HTTPException(status_code=404, detail="找不到这张照片")
    return photo


@router.get("/attendance/{team_id}/{year}/{month}/{day}")
def attendance_day_page(
    request: Request,
    team_id: int,
    year: int,
    month: int,
    day: int,
    user: User = Depends(require_team_scope),
    db: Session = Depends(get_db),
):
    team = db.get(Team, team_id)
    roster = get_roster(db, team_id, year, month)
    pairs = [(r.employee_id, team_id) for r in roster]
    entries = get_entries_for_day(db, pairs, year, month, day)
    excluded_default = get_left_yesterday_employee_ids(db, pairs, year, month, day)
    values = get_active_values(db)

    employees = []
    for r in roster:
        e = entries.get((r.employee_id, team_id))
        employees.append(
            {
                "id": r.employee_id,
                "name": r.employee.full_name,
                "am_value_id": e.am_value_id if e else None,
                "am_note": e.am_note if e else None,
                "pm_value_id": e.pm_value_id if e else None,
                "pm_note": e.pm_note if e else None,
                "evening_overtime": e.evening_overtime if e else False,
                "complete": is_entry_complete(e),
                "default_excluded": (r.employee_id, team_id) in excluded_default,
            }
        )

    values_json = [
        {"id": v.id, "code": v.code, "category": v.category.value, "requires_note": v.requires_note}
        for v in values
    ]

    py, pmn, pd = shift_day(year, month, day, -1)
    ny, nmn, nd = shift_day(year, month, day, 1)
    photos = get_daily_photos(db, team_id, year, month, day)

    return templates.TemplateResponse(
        request,
        "attendance_day.html",
        {
            "user": user,
            "active_nav": "dashboard",
            "team": team,
            "year": year,
            "month": month,
            "day": day,
            "employees": employees,
            "values": values_json,
            "prev": {"year": py, "month": pmn, "day": pd},
            "next": {"year": ny, "month": nmn, "day": nd},
            "photos": photos,
            "max_daily_photos": MAX_DAILY_PHOTOS,
        },
    )


@router.post("/attendance/{team_id}/{year}/{month}/{day}/photo")
def attendance_upload_photo(
    team_id: int,
    year: int,
    month: int,
    day: int,
    photo: UploadFile = File(...),
    user: User = Depends(require_team_scope),
    db: Session = Depends(get_db),
):
    if count_daily_photos(db, team_id, year, month, day) >= MAX_DAILY_PHOTOS:
        raise HTTPException(status_code=400, detail=f"今天最多只能传{MAX_DAILY_PHOTOS}张合照")
    upload_daily_photo(db, team_id, year, month, day, photo, uploaded_by=user.id)
    return {"status": "ok"}


@router.post("/attendance/{team_id}/{year}/{month}/{day}/photo/{photo_id}/retry-sync")
def attendance_retry_photo_sync(
    team_id: int,
    year: int,
    month: int,
    day: int,
    photo_id: int,
    user: User = Depends(require_team_scope),
    db: Session = Depends(get_db),
):
    photo = _get_scoped_photo(db, team_id, year, month, day, photo_id)
    try_sync_to_drive(db, photo)
    db.commit()
    return {"status": "ok", "drive_status": photo.drive_status.value}


@router.post("/attendance/{team_id}/{year}/{month}/{day}/photo/{photo_id}/delete")
def attendance_delete_photo(
    team_id: int,
    year: int,
    month: int,
    day: int,
    photo_id: int,
    user: User = Depends(require_team_scope),
    db: Session = Depends(get_db),
):
    photo = _get_scoped_photo(db, team_id, year, month, day, photo_id)
    warning = delete_daily_photo(db, photo)
    return {"status": "ok", "warning": warning}


@router.get("/attendance/{team_id}/{year}/{month}/{day}/photo/{photo_id}/file")
def attendance_photo_file(
    team_id: int,
    year: int,
    month: int,
    day: int,
    photo_id: int,
    user: User = Depends(require_team_scope),
    db: Session = Depends(get_db),
):
    photo = _get_scoped_photo(db, team_id, year, month, day, photo_id)
    path = resolve_path(photo.local_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path)


@router.post("/attendance/{team_id}/{year}/{month}/{day}/bulk")
def attendance_bulk(
    team_id: int,
    year: int,
    month: int,
    day: int,
    payload: BulkApplyRequest,
    user: User = Depends(require_team_scope),
    db: Session = Depends(get_db),
):
    if not claim_idempotency_key(db, payload.idempotency_key):
        return {"status": "duplicate_ignored"}

    valid_ids = _roster_employee_ids(db, team_id, year, month)
    target_ids = [eid for eid in payload.employee_ids if eid in valid_ids]
    if not target_ids:
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
    for eid in target_ids:
        entry = get_or_create_entry(db, eid, team_id, year, month, day, user.id)
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


@router.post("/attendance/{team_id}/{year}/{month}/{day}/{employee_id}")
def attendance_individual(
    team_id: int,
    year: int,
    month: int,
    day: int,
    employee_id: int,
    payload: IndividualEditRequest,
    user: User = Depends(require_team_scope),
    db: Session = Depends(get_db),
):
    if not claim_idempotency_key(db, payload.idempotency_key):
        return {"status": "duplicate_ignored"}

    valid_ids = _roster_employee_ids(db, team_id, year, month)
    if employee_id not in valid_ids:
        raise HTTPException(403, "该员工不在本班组当月花名册中")

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


@router.get("/attendance/{team_id}/{year}/{month}")
def attendance_month_grid(
    request: Request,
    team_id: int,
    year: int,
    month: int,
    user: User = Depends(require_team_scope),
    db: Session = Depends(get_db),
):
    team = db.get(Team, team_id)
    roster = get_roster(db, team_id, year, month)
    pairs = [(r.employee_id, team_id) for r in roster]
    total_days = days_in_month(year, month)
    all_entries = get_month_entries(db, pairs, year, month)
    value_codes = {v.id: v.code for v in db.query(AttendanceValue).all()}

    rows = []
    for r in roster:
        cells = []
        for day in range(1, total_days + 1):
            entry = all_entries[(r.employee_id, team_id)].get(day)
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
        rows.append({"employee_id": r.employee_id, "name": r.employee.full_name, "cells": cells})

    return templates.TemplateResponse(
        request,
        "attendance_month_grid.html",
        {
            "user": user,
            "active_nav": "dashboard",
            "team": team,
            "year": year,
            "month": month,
            "days": list(range(1, total_days + 1)),
            "rows": rows,
        },
    )
