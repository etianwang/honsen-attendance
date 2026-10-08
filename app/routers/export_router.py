import io
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_stats_access, require_team_scope
from app.database import get_db
from app.models import Team, User
from app.routers.stats_router import resolve_range
from app.services.excel_export import build_labor_stats_export, build_month_export, build_person_stats_export
from app.services.stats import labor_stats, person_range_category_summary, person_site_team_stats

router = APIRouter()

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_response(wb, filename: str) -> StreamingResponse:
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    # Content-Disposition header bytes must be latin-1; a Chinese filename needs
    # the RFC 5987 filename* form, with a plain ASCII fallback alongside it.
    encoded = quote(filename)
    disposition = f"attachment; filename=\"export.xlsx\"; filename*=UTF-8''{encoded}"
    return StreamingResponse(
        buf,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": disposition},
    )


@router.get("/export/{team_id}/{year}/{month}.xlsx")
def export_month(
    team_id: int,
    year: int,
    month: int,
    user: User = Depends(require_team_scope),
    db: Session = Depends(get_db),
):
    team = db.get(Team, team_id)
    wb = build_month_export(db, team, year, month)
    return _xlsx_response(wb, f"{team.name}_{year}年{month}月考勤.xlsx")


@router.get("/export/labor-stats.xlsx")
def export_labor_stats(
    scope: str = "month",
    year: int | None = None,
    month: int | None = None,
    quarter: int | None = None,
    half: int | None = None,
    start: str | None = None,
    end: str | None = None,
    user: User = Depends(require_stats_access),
    db: Session = Depends(get_db),
):
    today = date.today()
    year = year or today.year
    month = month or today.month
    start_date, end_date = resolve_range(scope, year, month, quarter, half, start, end)
    rows = labor_stats(db, start_date, end_date)
    wb = build_labor_stats_export(rows)
    labels = {"all": "累计", "month": f"{year}年{month}月", "quarter": f"{year}年第{quarter or 1}季度",
              "half": f"{year}年{'上' if (half or 1) == 1 else '下'}半年", "year": f"{year}年",
              "custom": f"{start}至{end}"}
    return _xlsx_response(wb, f"工地专业组人工统计_{labels.get(scope, scope)}.xlsx")


@router.get("/export/person-stats.xlsx")
def export_person_stats(
    scope: str = "month",
    year: int | None = None,
    month: int | None = None,
    quarter: int | None = None,
    half: int | None = None,
    start: str | None = None,
    end: str | None = None,
    user: User = Depends(require_stats_access),
    db: Session = Depends(get_db),
):
    today = date.today()
    year = year or today.year
    month = month or today.month
    start_date, end_date = resolve_range(scope, year, month, quarter, half, start, end)
    rows = person_site_team_stats(db, start_date, end_date)
    category_rows = person_range_category_summary(db, start_date, end_date)
    category_codes = sorted({code for r in category_rows for code in r["by_code_days"]})
    wb = build_person_stats_export(rows, category_rows, category_codes)
    labels = {"all": "累计", "month": f"{year}年{month}月", "quarter": f"{year}年第{quarter or 1}季度",
              "half": f"{year}年{'上' if (half or 1) == 1 else '下'}半年", "year": f"{year}年",
              "custom": f"{start}至{end}"}
    return _xlsx_response(wb, f"按人员统计_{labels.get(scope, scope)}.xlsx")
