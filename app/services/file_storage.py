import shutil
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings

MAX_PHOTO_DIMENSION = 1920
JPEG_QUALITY = 82


def _compress_to_jpeg(upload: UploadFile) -> BytesIO:
    """Every upload gets re-encoded to a size-capped JPEG before it touches
    disk (or Drive) — Drive storage is limited, and a raw phone photo can be
    5-10x larger than this with no visible difference for a group headcount
    photo. 1920px on the long side keeps individual faces in a team photo
    legible; exif_transpose() applies the phone's rotation metadata before
    re-encoding strips it, so portrait shots don't come out sideways."""
    upload.file.seek(0)
    try:
        img = Image.open(upload.file)
        img.load()
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="无法识别这个文件，请确认上传的是图片")
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((MAX_PHOTO_DIMENSION, MAX_PHOTO_DIMENSION), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    buf.seek(0)
    return buf


def _write(rel_path: str, upload: UploadFile) -> str:
    full_path = Path(settings.upload_dir) / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    compressed = _compress_to_jpeg(upload)
    with open(full_path, "wb") as f:
        shutil.copyfileobj(compressed, f)
    return rel_path


def save_avatar(employee_id: int, upload: UploadFile) -> str:
    return _write(f"avatars/{employee_id}.jpg", upload)


def save_daily_photo(team_id: int, year: int, month: int, day: int, upload: UploadFile) -> str:
    return _write(f"daily_photos/{team_id}_{year}_{month:02d}_{day:02d}.jpg", upload)


def resolve_path(rel_path: str) -> Path:
    return Path(settings.upload_dir) / rel_path
