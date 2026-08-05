from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Employee, MonthlyRoster, User, UserRole


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="未登录")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        # A stale cookie pointing at a deleted/deactivated user must not survive —
        # otherwise /login's "already logged in" check keeps bouncing it to
        # /dashboard, which bounces right back here, forever.
        request.session.clear()
        raise HTTPException(status_code=401, detail="未登录")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def require_team_scope(team_id: int, user: User = Depends(get_current_user)) -> User:
    """Server-side enforcement: a team_lead can only ever touch their own team_id,
    no matter what the client sends — this is checked on every request, not just
    hidden in the UI."""
    if user.role == UserRole.admin:
        return user
    if user.team_id != team_id:
        raise HTTPException(status_code=403, detail="无权访问该班组的数据")
    return user


def require_employee_scope(
    employee_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Employee:
    """A team_lead may only view/edit an employee who has, at some point, been
    on their team's roster; admin can access anyone."""
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="找不到该员工")
    if user.role == UserRole.admin:
        return employee
    on_team = db.scalar(
        select(MonthlyRoster.id)
        .where(MonthlyRoster.employee_id == employee_id, MonthlyRoster.team_id == user.team_id)
        .limit(1)
    )
    if on_team is None:
        raise HTTPException(status_code=403, detail="无权访问该员工信息")
    return employee
