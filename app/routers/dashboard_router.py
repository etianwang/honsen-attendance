from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models import Team, User, UserRole
from app.templates_env import templates

router = APIRouter()


@router.get("/")
def root(user: User = Depends(get_current_user)):
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/dashboard")
def dashboard(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today = date.today()
    if user.role == UserRole.admin:
        teams = db.scalars(select(Team).where(Team.is_active.is_(True)).order_by(Team.name)).all()
        return templates.TemplateResponse(
            request,
            "dashboard_admin.html",
            {"user": user, "active_nav": "dashboard", "teams": teams, "today": today},
        )
    return RedirectResponse(
        url=f"/attendance/{user.team_id}/{today.year}/{today.month}/{today.day}", status_code=303
    )
