from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin
from app.database import get_db
from app.models import User
from app.services.stats import (
    half_year_range,
    labor_stats,
    month_range,
    person_range_category_summary,
    person_site_team_stats,
    pivot_labor_stats,
    quarter_range,
    year_range,
)
from app.templates_env import templates

router = APIRouter()


def resolve_range(
    scope: str,
    year: int | None,
    month: int | None,
    quarter: int | None,
    half: int | None,
    start: str | None,
    end: str | None,
) -> tuple[date | None, date | None]:
    today = date.today()
    year = year or today.year
    if scope == "all":
        return None, None
    if scope == "month":
        return month_range(year, month or today.month)
    if scope == "quarter":
        return quarter_range(year, quarter or 1)
    if scope == "half":
        return half_year_range(year, half or 1)
    if scope == "year":
        return year_range(year)
    if scope == "custom":
        if not start or not end:
            raise HTTPException(status_code=400, detail="自定义范围需要起止日期")
        return datetime.strptime(start, "%Y-%m-%d").date(), datetime.strptime(end, "%Y-%m-%d").date()
    raise HTTPException(status_code=400, detail="未知的口径")


@router.get("/admin/stats")
def stats_page(
    request: Request,
    scope: str = "month",
    year: int | None = None,
    month: int | None = None,
    quarter: int | None = None,
    half: int | None = None,
    start: str | None = None,
    end: str | None = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """工地×班组 and 按人员 are the same underlying query (person_site_team_stats
    is just labor_stats with the employee dimension kept), the same date-range
    picker, and the same "用于报价/成本核算" purpose — one page, two tabs,
    instead of two separate nav entries and two round trips to pick the same
    range twice."""
    today = date.today()
    year = year or today.year
    month = month or today.month
    start_date, end_date = resolve_range(scope, year, month, quarter, half, start, end)
    person_rows = person_site_team_stats(db, start_date, end_date)
    person_category_rows = person_range_category_summary(db, start_date, end_date)
    category_codes = sorted({code for r in person_category_rows for code in r["by_code_days"]})
    pivot = pivot_labor_stats(labor_stats(db, start_date, end_date))
    return templates.TemplateResponse(
        request,
        "admin/stats.html",
        {
            "user": user,
            "active_nav": "stats",
            "scope": scope,
            "year": year,
            "month": month,
            "quarter": quarter or 1,
            "half": half or 1,
            "start": start or "",
            "end": end or "",
            "start_date": start_date,
            "end_date": end_date,
            "pivot": pivot,
            "person_rows": person_rows,
            "person_category_rows": person_category_rows,
            "category_codes": category_codes,
        },
    )
