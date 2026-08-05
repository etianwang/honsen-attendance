from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_team_scope
from app.auth.security import verify_password
from app.database import get_db
from app.models import Team, User
from app.services.roster_service import (
    add_employees_bulk,
    copy_forward,
    get_roster,
    list_present_candidates,
    remove_employee_from_roster,
)
from app.templates_env import templates

router = APIRouter()


@router.get("/roster/{team_id}")
def roster_page(
    request: Request,
    team_id: int,
    year: int | None = None,
    month: int | None = None,
    user: User = Depends(require_team_scope),
    db: Session = Depends(get_db),
):
    today = date.today()
    year = year or today.year
    month = month or today.month
    team = db.get(Team, team_id)
    roster = get_roster(db, team_id, year, month)
    candidates = list_present_candidates(db, team_id, year, month)
    return templates.TemplateResponse(
        request,
        "roster.html",
        {
            "user": user,
            "active_nav": "roster",
            "team": team,
            "year": year,
            "month": month,
            "roster": roster,
            "candidates": candidates,
        },
    )


@router.post("/roster/{team_id}/copy-forward")
def roster_copy_forward(
    team_id: int,
    year: int = Form(...),
    month: int = Form(...),
    user: User = Depends(require_team_scope),
    db: Session = Depends(get_db),
):
    added = copy_forward(db, team_id, year, month)
    return RedirectResponse(
        url=f"/roster/{team_id}?year={year}&month={month}&ok=已从上月复制{added}人", status_code=303
    )


@router.post("/roster/{team_id}/add-bulk")
def roster_add_bulk(
    team_id: int,
    year: int = Form(...),
    month: int = Form(...),
    employee_ids: list[int] = Form(default=[]),
    user: User = Depends(require_team_scope),
    db: Session = Depends(get_db),
):
    if not employee_ids:
        return RedirectResponse(url=f"/roster/{team_id}?year={year}&month={month}&err=请先选择要添加的人", status_code=303)
    added = add_employees_bulk(db, team_id, year, month, employee_ids)
    return RedirectResponse(url=f"/roster/{team_id}?year={year}&month={month}&ok=已添加{added}人", status_code=303)


@router.post("/roster/{team_id}/remove")
def roster_remove(
    team_id: int,
    year: int = Form(...),
    month: int = Form(...),
    employee_id: int = Form(...),
    confirm_password: str = Form(...),
    user: User = Depends(require_team_scope),
    db: Session = Depends(get_db),
):
    if not verify_password(confirm_password, user.password_hash):
        return RedirectResponse(
            url=f"/roster/{team_id}?year={year}&month={month}&err=密码不对，未移除", status_code=303
        )
    try:
        removed = remove_employee_from_roster(db, team_id, year, month, employee_id)
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url=f"/roster/{team_id}?year={year}&month={month}&err=该员工本月已有考勤记录，不能直接移除",
            status_code=303,
        )
    msg = "已移除" if removed else "未找到该员工"
    return RedirectResponse(url=f"/roster/{team_id}?year={year}&month={month}&ok={msg}", status_code=303)
