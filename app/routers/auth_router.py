from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import verify_password
from app.database import get_db
from app.models import User
from app.templates_env import templates

router = APIRouter()


@router.get("/login")
def login_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"user": None})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request, "login.html", {"user": None, "error": "账号或密码不对"}, status_code=401
        )
    request.session["user_id"] = user.id
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
