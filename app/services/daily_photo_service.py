from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DailyTeamPhoto, DriveSyncStatus
from app.services import cos_service
from app.services.file_storage import resolve_path, save_daily_photo

MAX_DAILY_PHOTOS = 6


def get_daily_photos(db: Session, team_id: int, year: int, month: int, day: int) -> list[DailyTeamPhoto]:
    return list(
        db.scalars(
            select(DailyTeamPhoto)
            .where(
                DailyTeamPhoto.team_id == team_id,
                DailyTeamPhoto.year == year,
                DailyTeamPhoto.month == month,
                DailyTeamPhoto.day == day,
            )
            .order_by(DailyTeamPhoto.uploaded_at)
        )
    )


def count_daily_photos(db: Session, team_id: int, year: int, month: int, day: int) -> int:
    return db.scalar(
        select(func.count()).select_from(DailyTeamPhoto).where(
            DailyTeamPhoto.team_id == team_id,
            DailyTeamPhoto.year == year,
            DailyTeamPhoto.month == month,
            DailyTeamPhoto.day == day,
        )
    )


def get_photo_by_id(db: Session, photo_id: int) -> DailyTeamPhoto | None:
    return db.get(DailyTeamPhoto, photo_id)


def upload_daily_photo(
    db: Session, team_id: int, year: int, month: int, day: int, upload: UploadFile, uploaded_by: int
) -> DailyTeamPhoto:
    """Always adds a new photo — a day can hold up to MAX_DAILY_PHOTOS of
    them (clock-in, clock-out, overtime clock-in/out, whichever subset
    actually got photographed, in no fixed order), so this never replaces an
    existing one the way a single-photo-per-day design would. Callers must
    check count_daily_photos() against MAX_DAILY_PHOTOS before calling this —
    enforced in the router so the cap produces a friendly error, not a
    silent 7th photo."""
    rel_path = save_daily_photo(team_id, year, month, day, upload)
    photo = DailyTeamPhoto(team_id=team_id, year=year, month=month, day=day, local_path=rel_path, uploaded_by=uploaded_by)
    db.add(photo)
    db.flush()

    try_sync_to_drive(db, photo)
    db.commit()
    return photo


def delete_daily_photo(db: Session, photo: DailyTeamPhoto) -> str | None:
    """Deletes the local file and the DB row unconditionally, and best-effort
    deletes the remote (COS) copy too if one was ever uploaded. Returns a
    warning string if that remote delete failed, so the caller can surface
    it without blocking the (already-succeeded) local deletion — a photo the
    team lead asked to remove must actually disappear from their page even
    if COS is unreachable right now."""
    remote_warning = None
    if photo.drive_file_id:
        try:
            cos_service.delete_file(photo.drive_file_id)
        except Exception as exc:  # noqa: BLE001
            remote_warning = f"本地照片已删除，但云端 COS 文件删除失败：{str(exc)[:200]}"
    local_path = resolve_path(photo.local_path)
    if local_path.exists():
        local_path.unlink()
    db.delete(photo)
    db.commit()
    return remote_warning


def try_sync_to_drive(db: Session, photo: DailyTeamPhoto) -> None:
    """Best-effort: local file is already durably saved regardless of outcome
    here. Field/function names still say "drive"/"drive_*" for historical
    reasons (this originally synced to Google Drive) — the active backend is
    now Tencent COS, and drive_file_id holds the COS object key instead of a
    Drive file id."""
    if not cos_service.is_configured():
        photo.drive_status = DriveSyncStatus.pending
        photo.drive_error = None
        return
    local_path: Path = resolve_path(photo.local_path)
    # Reuses the local filename's own unique stem (it already has a random
    # suffix per photo, see file_storage.save_daily_photo) so multiple
    # photos from the same day never collide on the same COS object key.
    object_key = f"daily_photos/{local_path.name}"
    try:
        file_key = cos_service.upload_file(local_path, object_key)
        photo.drive_file_id = file_key
        photo.drive_status = DriveSyncStatus.uploaded
        photo.drive_error = None
    except Exception as exc:  # noqa: BLE001 — any COS/auth/network failure must not lose the local photo
        photo.drive_status = DriveSyncStatus.failed
        photo.drive_error = str(exc)[:255]
