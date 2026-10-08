import logging
import os
import shutil
import tempfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.auth.dependencies import require_admin
from app.auth.security import hash_password
from app.database import SessionLocal, engine, get_db
from app.config import settings
from app.models import AttendanceValue, Team, User, UserRole, ValueCategory
from app.services.database_backup_service import create_backup, restore_backup, upgrade_schema
from app.templates_env import templates

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
backup_router = APIRouter(prefix="/admin")
logger = logging.getLogger(__name__)


def require_backup_admin(request: Request) -> User:
    """Authenticates then closes its DB session before pg_restore takes table locks."""
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="未登录")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            request.session.clear()
            raise HTTPException(status_code=401, detail="未登录")
        if user.role != UserRole.admin:
            raise HTTPException(status_code=403, detail="需要管理员权限")
        return user


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
            "tab": tab if tab in ("teams", "accounts", "values", "data") else "teams",
            "teams": teams,
            "users": users,
            "values": values,
            "UserRole": UserRole,
        },
    )


@backup_router.get("/backup")
def download_database_backup(user: User = Depends(require_backup_admin)):
    """Exports the database only; COS credentials remain on the server."""
    descriptor, filename = tempfile.mkstemp(prefix="attendance-", suffix=".dump")
    os.close(descriptor)
    backup_path = Path(filename)
    try:
        create_backup(settings.database_url, backup_path)
    except Exception:  # noqa: BLE001 - do not reveal connection details to the browser
        backup_path.unlink(missing_ok=True)
        logger.exception("Database backup failed")
        raise HTTPException(status_code=503, detail="数据库备份失败，请确认服务器已安装 pg_dump 且数据库可访问。")
    return FileResponse(
        backup_path,
        media_type="application/octet-stream",
        filename=f"attendance-{date.today():%Y%m%d}.dump",
        background=BackgroundTask(backup_path.unlink, missing_ok=True),
    )


@backup_router.post("/backup/restore")
async def restore_database_backup(
    request: Request,
    backup: UploadFile = File(...),
    confirmation: str = Form(...),
    user: User = Depends(require_backup_admin),
):
    if confirmation.strip() != "恢复":
        return RedirectResponse(url="/admin/settings?tab=data&err=请输入恢复以确认覆盖当前数据", status_code=303)
    if not (backup.filename or "").lower().endswith(".dump"):
        return RedirectResponse(url="/admin/settings?tab=data&err=请选择下载的.dump备份文件", status_code=303)

    descriptor, filename = tempfile.mkstemp(prefix="attendance-restore-", suffix=".dump")
    os.close(descriptor)
    backup_path = Path(filename)
    try:
        with backup_path.open("wb") as file:
            shutil.copyfileobj(backup.file, file)
        engine.dispose()
        restore_backup(settings.database_url, backup_path)
        upgrade_schema()
    except Exception:  # noqa: BLE001 - do not reveal connection details to the browser
        logger.exception("Database restore failed")
        return RedirectResponse(url="/admin/settings?tab=data&err=恢复失败，当前数据库可能未完整恢复，请联系管理员", status_code=303)
    finally:
        backup_path.unlink(missing_ok=True)
        await backup.close()
    request.session.clear()
    return RedirectResponse(url="/login?ok=数据库已恢复，请重新登录", status_code=303)


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
    if role not in ("admin", "team_lead", "auditor"):
        return RedirectResponse(url="/admin/settings?tab=accounts&err=无效的账号角色", status_code=303)
    user_role = UserRole(role)
    if user_role == UserRole.team_lead and not team_id:
        return RedirectResponse(url="/admin/settings?tab=accounts&err=班组长账号必须选择所属班组", status_code=303)
    db.add(
        User(
            username=username,
            password_hash=hash_password(password),
            display_name=display_name.strip(),
            role=user_role,
            team_id=int(team_id) if user_role == UserRole.team_lead else None,
        )
    )
    db.commit()
    return RedirectResponse(url="/admin/settings?tab=accounts&ok=已创建账号", status_code=303)


@router.post("/users/{user_id}/change-team")
def admin_users_change_team(user_id: int, team_id: str = Form(""), db: Session = Depends(get_db)):
    """Lets an existing team_lead be reassigned to a different team — needed
    once their original team gets deactivated, or they simply move teams.
    Previously team_id could only be set once, at account creation, with no
    way to change it afterward."""
    target = db.get(User, user_id)
    if target is None:
        return RedirectResponse(url="/admin/settings?tab=accounts&err=找不到该账号", status_code=303)
    if target.role != UserRole.team_lead:
        return RedirectResponse(url="/admin/settings?tab=accounts&err=只有班组长账号才需要绑定班组", status_code=303)
    if not team_id:
        return RedirectResponse(url="/admin/settings?tab=accounts&err=班组长账号必须绑定一个班组", status_code=303)
    team = db.get(Team, int(team_id))
    if team is None:
        return RedirectResponse(url="/admin/settings?tab=accounts&err=找不到该班组", status_code=303)
    target.team_id = team.id
    db.commit()
    return RedirectResponse(url=f"/admin/settings?tab=accounts&ok=已把{target.username}的班组改成{team.name}", status_code=303)


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
