from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyTeamPhoto, DriveSyncStatus
from app.services import cos_service
from app.services.file_storage import resolve_path, save_daily_photo


def get_daily_photo(db: Session, team_id: int, year: int, month: int, day: int) -> DailyTeamPhoto | None:
    return db.scalar(
        select(DailyTeamPhoto).where(
            DailyTeamPhoto.team_id == team_id,
            DailyTeamPhoto.year == year,
            DailyTeamPhoto.month == month,
            DailyTeamPhoto.day == day,
        )
    )


def upload_daily_photo(
    db: Session, team_id: int, year: int, month: int, day: int, upload: UploadFile, uploaded_by: int
) -> DailyTeamPhoto:
    rel_path = save_daily_photo(team_id, year, month, day, upload)

    photo = get_daily_photo(db, team_id, year, month, day)
    if photo is None:
        photo = DailyTeamPhoto(team_id=team_id, year=year, month=month, day=day, local_path=rel_path, uploaded_by=uploaded_by)
        db.add(photo)
    else:
        # Replacing an already-synced photo — clean up the old remote copy
        # first (best-effort) so replacing never leaves an orphaned object
        # sitting in COS forever under the old photo's key.
        if photo.drive_file_id:
            try:
                cos_service.delete_file(photo.drive_file_id)
            except Exception:  # noqa: BLE001 — replacing the photo must succeed even if the old remote copy can't be cleaned up
                pass
        photo.local_path = rel_path
        photo.uploaded_by = uploaded_by
        photo.drive_file_id = None
        photo.drive_status = DriveSyncStatus.pending
        photo.drive_error = None
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
    object_key = f"daily_photos/{photo.team_id}_{photo.year}-{photo.month:02d}-{photo.day:02d}{local_path.suffix}"
    try:
        file_key = cos_service.upload_file(local_path, object_key)
        photo.drive_file_id = file_key
        photo.drive_status = DriveSyncStatus.uploaded
        photo.drive_error = None
    except Exception as exc:  # noqa: BLE001 — any COS/auth/network failure must not lose the local photo
        photo.drive_status = DriveSyncStatus.failed
        photo.drive_error = str(exc)[:255]
