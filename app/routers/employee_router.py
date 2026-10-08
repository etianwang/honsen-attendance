from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth.dependencies import get_current_user, require_admin, require_employee_edit_scope, require_employee_scope, require_stats_access
from app.auth.security import verify_password
from app.database import get_db
from app.models import DailyTeamPhoto, Employee, EmployeeStatus, User
from app.services.file_storage import resolve_path, save_avatar
from app.services.roster_service import all_employees_with_current_teams
from app.templates_env import templates

router = APIRouter()

BLOOD_TYPES = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "不详"]


@router.get("/admin/employees")
def admin_employee_directory(
    request: Request,
    q: str | None = None,
    user: User = Depends(require_stats_access),
    db: Session = Depends(get_db),
):
    """Cross-team employee directory — unlike a team's own 花名册 page (scoped
    to one team), this lists everyone regardless of which team (if any)
    they're on right now, so admin can find/manage someone without knowing
    in advance which team to look under."""
    today = date.today()
    rows = all_employees_with_current_teams(db, today.year, today.month, q)
    return templates.TemplateResponse(
        request,
        "admin/employees.html",
        {"user": user, "active_nav": "employees", "rows": rows, "q": q or "", "EmployeeStatus": EmployeeStatus},
    )


@router.get("/admin/photos")
def audit_daily_photos(
    request: Request,
    selected_date: date | None = None,
    user: User = Depends(require_stats_access),
    db: Session = Depends(get_db),
):
    selected_date = selected_date or date.today()
    photos = db.scalars(
        select(DailyTeamPhoto)
        .options(joinedload(DailyTeamPhoto.team))
        .where(
            DailyTeamPhoto.year == selected_date.year,
            DailyTeamPhoto.month == selected_date.month,
            DailyTeamPhoto.day == selected_date.day,
        )
        .order_by(DailyTeamPhoto.team_id, DailyTeamPhoto.uploaded_at)
    ).all()
    return templates.TemplateResponse(
        request,
        "admin/daily_photos.html",
        {
            "user": user,
            "active_nav": "photos",
            "selected_date": selected_date,
            "previous_date": selected_date - timedelta(days=1),
            "next_date": selected_date + timedelta(days=1),
            "photos": photos,
        },
    )


@router.get("/admin/photos/{photo_id}/file")
def audit_daily_photo_file(
    photo_id: int,
    user: User = Depends(require_stats_access),
    db: Session = Depends(get_db),
):
    photo = db.get(DailyTeamPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="找不到这张照片")
    path = resolve_path(photo.local_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="照片文件不存在")
    return FileResponse(path)


@router.post("/admin/employees/add")
def admin_employee_create(
    full_name: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    full_name = full_name.strip()
    if not full_name:
        return RedirectResponse(url="/admin/employees?err=姓名不能为空", status_code=303)
    if db.scalar(select(Employee).where(Employee.full_name == full_name)):
        return RedirectResponse(url=f"/admin/employees?err=已经有一个叫{full_name}的员工了，姓名不能重复", status_code=303)
    employee = Employee(full_name=full_name)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return RedirectResponse(url=f"/employee/{employee.id}?ok=已创建，请补充信息", status_code=303)


@router.get("/employee/{employee_id}")
def employee_profile(
    request: Request,
    employee: Employee = Depends(require_employee_scope),
    user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request,
        "employee_profile.html",
        {"user": user, "employee": employee, "blood_types": BLOOD_TYPES, "EmployeeStatus": EmployeeStatus},
    )


@router.post("/employee/{employee_id}")
def employee_profile_update(
    employee_id: int,
    full_name: str = Form(...),
    status: str = Form(...),
    phone: str = Form(""),
    blood_type: str = Form(""),
    emergency_contact_name: str = Form(""),
    emergency_contact_phone: str = Form(""),
    employee: Employee = Depends(require_employee_edit_scope),
    db: Session = Depends(get_db),
):
    # employees.id (already stable, never shown/editable) is what every
    # roster/attendance row actually points to — renaming full_name here
    # (e.g. fixing a typo) never touches that id, so history stays intact.
    full_name = full_name.strip()
    if not full_name:
        return RedirectResponse(url=f"/employee/{employee_id}?err=姓名不能为空", status_code=303)
    conflict = db.scalar(select(Employee).where(Employee.full_name == full_name, Employee.id != employee_id))
    if conflict is not None:
        return RedirectResponse(
            url=f"/employee/{employee_id}?err=已经有一个叫{full_name}的员工了，姓名不能重复", status_code=303
        )
    employee.full_name = full_name
    employee.status = EmployeeStatus(status)
    employee.phone = phone.strip() or None
    employee.blood_type = blood_type.strip() or None
    employee.emergency_contact_name = emergency_contact_name.strip() or None
    employee.emergency_contact_phone = emergency_contact_phone.strip() or None
    db.commit()
    return RedirectResponse(url=f"/employee/{employee_id}?ok=已保存", status_code=303)


@router.post("/employee/{employee_id}/avatar")
def employee_avatar_upload(
    employee_id: int,
    avatar: UploadFile = File(...),
    employee: Employee = Depends(require_employee_edit_scope),
    db: Session = Depends(get_db),
):
    rel_path = save_avatar(employee_id, avatar)
    employee.avatar_path = rel_path
    db.commit()
    return RedirectResponse(url=f"/employee/{employee_id}?ok=头像已更新", status_code=303)


@router.post("/employee/{employee_id}/delete")
def employee_delete(
    employee_id: int,
    confirm_password: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """永久删除员工记录——只有管理员能做，且只有在这个人从没上过任何一个月的
    花名册（因此也没有任何考勤历史）时才会成功。只要有一丁点历史，数据库的外键
    约束会直接挡住这个删除（跟"从花名册移除"那个操作背后是同一道防线），这样
    "人员的删减比班组的删减更谨慎"就不是靠人工记住规则，而是数据库层面强制的。
    这个操作还要求再输一遍管理员自己的登录密码确认——比普通的浏览器 confirm()
    弹窗多一道真正的门槛，防止手滑或者别人借用已登录的电脑乱点。"""
    if not verify_password(confirm_password, user.password_hash):
        return RedirectResponse(url=f"/employee/{employee_id}?err=密码不对，未删除", status_code=303)
    employee = db.get(Employee, employee_id)
    if employee is None:
        return RedirectResponse(url="/dashboard?err=找不到该员工", status_code=303)
    avatar_path = employee.avatar_path
    try:
        db.delete(employee)
        db.commit()
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url=f"/employee/{employee_id}?err=这个人有花名册/考勤历史，不能永久删除，只能从某个月的花名册里移除",
            status_code=303,
        )
    if avatar_path:
        path = resolve_path(avatar_path)
        if path.exists():
            path.unlink()
    return RedirectResponse(url="/dashboard?ok=已永久删除该员工", status_code=303)


@router.get("/employee/{employee_id}/avatar-file")
def employee_avatar_file(employee_id: int, employee: Employee = Depends(require_employee_scope)):
    if not employee.avatar_path:
        raise HTTPException(status_code=404, detail="还没有头像")
    path = resolve_path(employee.avatar_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path)
