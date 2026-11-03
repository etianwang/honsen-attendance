import json

from fastapi.templating import Jinja2Templates

from app.config import settings


templates = Jinja2Templates(directory="app/templates")
templates.env.globals["app_name"] = settings.app_name


def _tojson(value) -> str:
    # Guards against a stray "</script>" in embedded data breaking out of its tag.
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


templates.env.filters["tojson"] = _tojson
