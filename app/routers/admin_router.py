from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin
from app.auth.security import hash_password
from app.database import get_db
from app.models import AttendanceValue, Team, User, UserRole, ValueCategory
from app.templates_env import templates

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


@router.get("/settings")
def admin_settings(
    request: Request,
    tab: str = "teams",
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    teams = db.scalars(select(Team).order_by(Team.name)).all()
    users = db.scalars(select(User).order_by(User.role, User.username)).all()
    values = db.scalars(select(AttendanceValue).order_by(AttendanceValue.category, AttendanceValue.sort_order)).all()
    return templates.TemplateResponse(
        request,
        "admin/settings.html",
        {
            "user": user,
            "active_nav": "settings",
            "tab": tab if tab in ("teams", "accounts", "values") else "teams",
            "teams": teams,
            "users": users,
            "values": values,
            "UserRole": UserRole,
        },
    )


@router.post("/teams/add")
def admin_teams_add(name: str = Form(...), db: Session = Depends(get_db)):
    name = name.strip()
    if name and not db.scalar(select(Team).where(Team.name == name)):
        db.add(Team(name=name))
        db.commit()
    return RedirectResponse(url="/admin/settings?tab=teams&ok=已添加班组", status_code=303)


@router.post("/teams/{team_id}/rename")
def admin_teams_rename(team_id: int, name: str = Form(...), db: Session = Depends(get_db)):
    team = db.get(Team, team_id)
    if team is None:
        return RedirectResponse(url="/admin/settings?tab=teams&err=找不到该班组", status_code=303)
    name = name.strip()
    if not name:
        return RedirectResponse(url="/admin/settings?tab=teams&err=班组名称不能为空", status_code=303)
    conflict = db.scalar(select(Team).where(Team.name == name, Team.id != team_id))
    if conflict is not None:
        return RedirectResponse(url="/admin/settings?tab=teams&err=已经有一个同名的班组了", status_code=303)
    team.name = name
    db.commit()
    return RedirectResponse(url="/admin/settings?tab=teams&ok=已重命名", status_code=303)


@router.post("/teams/{team_id}/toggle-active")
def admin_teams_toggle_active(team_id: int, db: Session = Depends(get_db)):
    """"删除"班组实际上是停用（is_active=False），不做真删除——历史花名册/考勤/
    统计数据都还挂在这个 team_id 下，删了会破坏这些记录；员工本身在 employees
    表里本来就和班组没有强绑定，班组停不停用都不影响员工信息还在。"""
    team = db.get(Team, team_id)
    if team is None:
        return RedirectResponse(url="/admin/settings?tab=teams&err=找不到该班组", status_code=303)
    team.is_active = not team.is_active
    db.commit()
    msg = "已停用" if not team.is_active else "已恢复启用"
    return RedirectResponse(url=f"/admin/settings?tab=teams&ok={msg}", status_code=303)


@router.post("/users/add")
def admin_users_add(
    username: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(...),
    role: str = Form(...),
    team_id: str = Form(""),
    db: Session = Depends(get_db),
):
    username = username.strip()
    if db.scalar(select(User).where(User.username == username)):
        return RedirectResponse(url="/admin/settings?tab=accounts&err=账号已存在", status_code=303)
    user_role = UserRole.admin if role == "admin" else UserRole.team_lead
    if user_role == UserRole.team_lead and not team_id:
        return RedirectResponse(url="/admin/settings?tab=accounts&err=班组长账号必须选择所属班组", status_code=303)
    db.add(
        User(
            username=username,
            password_hash=hash_password(password),
            display_name=display_name.strip(),
            role=user_role,
            team_id=int(team_id) if (user_role == UserRole.team_lead and team_id) else None,
        )
    )
    db.commit()
    return RedirectResponse(url="/admin/settings?tab=accounts&ok=已创建账号", status_code=303)


@router.post("/users/{user_id}/reset-password")
def admin_reset_password(user_id: int, new_password: str = Form(...), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        return RedirectResponse(url="/admin/settings?tab=accounts&err=找不到该账号", status_code=303)
    target.password_hash = hash_password(new_password)
    db.commit()
    return RedirectResponse(url=f"/admin/settings?tab=accounts&ok=已重置{target.username}的密码", status_code=303)


@router.post("/users/{user_id}/toggle-active")
def admin_toggle_active(user_id: int, db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        return RedirectResponse(url="/admin/settings?tab=accounts&err=找不到该账号", status_code=303)
    target.is_active = not target.is_active
    db.commit()
    return RedirectResponse(url="/admin/settings?tab=accounts&ok=已更新账号状态", status_code=303)


@router.post("/values/add")
def admin_values_add(
    code: str = Form(...),
    category: str = Form(...),
    requires_note: bool = Form(False),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
):
    code = code.strip()
    if code and not db.scalar(select(AttendanceValue).where(AttendanceValue.code == code)):
        db.add(
            AttendanceValue(
                code=code,
                category=ValueCategory.worksite if category == "worksite" else ValueCategory.nonwork,
                requires_note=requires_note,
                sort_order=sort_order,
            )
        )
        db.commit()
    return RedirectResponse(url="/admin/settings?tab=values&ok=已添加", status_code=303)


@router.post("/values/{value_id}/update")
def admin_values_update(
    value_id: int,
    code: str = Form(...),
    category: str = Form(...),
    requires_note: bool = Form(False),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
):
    value = db.get(AttendanceValue, value_id)
    if value is None:
        return RedirectResponse(url="/admin/settings?tab=values&err=找不到该值", status_code=303)
    code = code.strip()
    if not code:
        return RedirectResponse(url="/admin/settings?tab=values&err=名称不能为空", status_code=303)
    conflict = db.scalar(select(AttendanceValue).where(AttendanceValue.code == code, AttendanceValue.id != value_id))
    if conflict is not None:
        return RedirectResponse(url="/admin/settings?tab=values&err=已经有一个同名的值了", status_code=303)
    value.code = code
    value.category = ValueCategory.worksite if category == "worksite" else ValueCategory.nonwork
    value.requires_note = requires_note
    value.sort_order = sort_order
    db.commit()
    return RedirectResponse(url="/admin/settings?tab=values&ok=已保存", status_code=303)


@router.post("/values/{value_id}/toggle-active")
def admin_values_toggle(value_id: int, db: Session = Depends(get_db)):
    value = db.get(AttendanceValue, value_id)
    if value is None:
        return RedirectResponse(url="/admin/settings?tab=values&err=找不到该值", status_code=303)
    value.is_active = not value.is_active
    db.commit()
    return RedirectResponse(url="/admin/settings?tab=values&ok=已更新", status_code=303)
