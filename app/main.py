from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import NotModifiedResponse
from starlette.types import Scope

from app.config import settings
from app.routers import (
    admin_attendance_router,
    admin_router,
    attendance_router,
    auth_router,
    dashboard_router,
    employee_router,
    export_router,
    roster_router,
    stats_router,
)


class RevalidatingStaticFiles(StaticFiles):
    """Forces every static asset request to revalidate with the server
    (ETag/If-None-Match) instead of trusting the browser's heuristic
    freshness window — without this, field devices can silently keep
    running yesterday's JS/CSS for hours after a deploy, with no visible
    sign anything is stale."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        if not isinstance(response, NotModifiedResponse):
            response.headers["cache-control"] = "no-cache"
        return response


app = FastAPI(title="埃塞俄比亚考勤系统")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")
app.mount("/static", RevalidatingStaticFiles(directory="app/static"), name="static")


@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
    wants_html = "text/html" in request.headers.get("accept", "")
    if exc.status_code == 401 and wants_html:
        return RedirectResponse(url="/login", status_code=303)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.include_router(auth_router.router)
app.include_router(dashboard_router.router)
app.include_router(roster_router.router)
app.include_router(employee_router.router)
app.include_router(admin_attendance_router.router)
app.include_router(attendance_router.router)
app.include_router(admin_router.router)
app.include_router(stats_router.router)
app.include_router(export_router.router)
