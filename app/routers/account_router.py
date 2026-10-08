from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.security import hash_password, verify_password
from app.database import get_db
from app.models import User
from app.templates_env import templates

router = APIRouter()


@router.get("/account/password")
def password_form(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(request, "account_password.html", {"user": user, "active_nav": "account"})


@router.post("/account/password")
def change_own_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(current_password, user.password_hash):
        return RedirectResponse(url="/account/password?err=当前密码不正确", status_code=303)
    user.password_hash = hash_password(new_password)
    db.commit()
    return RedirectResponse(url="/account/password?ok=密码已修改", status_code=303)
