"""Google Drive upload for daily team photos, authorized as the operator's
own personal Google account (OAuth), not a service account.

A service account has zero storage quota of its own — it can only create
files inside a Shared Drive, which requires a paid Google Workspace plan.
A personal Gmail account has no Shared Drives, so uploads must happen as
that real account instead: a one-time interactive login (see
scripts/gdrive_oauth_setup.py) captures a refresh token, cached to
GOOGLE_DRIVE_OAUTH_TOKEN_PATH; every upload/delete after that reuses and
auto-refreshes it, no further login needed.

Photos are always saved to local disk first (see file_storage.py) — this
module is only responsible for best-effort syncing that local copy onward to
Drive. A failure here never loses the photo; it just leaves the row's
drive_status as 'pending'/'failed' for a later retry.
"""

from pathlib import Path

from app.config import settings

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class DriveNotConfigured(Exception):
    pass


def is_configured() -> bool:
    return bool(settings.google_drive_folder_id) and Path(settings.google_drive_oauth_token_path).exists()


def _credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path = Path(settings.google_drive_oauth_token_path)
    if not token_path.exists():
        raise DriveNotConfigured(
            "还没有完成 Google 账号授权，请先运行一次 scripts/gdrive_oauth_setup.py 做登录授权"
        )
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _service():
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=_credentials(), cache_discovery=False)


def upload_file(local_path: Path, drive_filename: str, mime_type: str = "image/jpeg") -> str:
    """Uploads local_path to the configured Drive folder. Returns the new
    file's Drive ID. Raises DriveNotConfigured if not set up yet, or lets the
    underlying google-api-python-client exception propagate for any other
    failure (auth error, network, quota, ...) — callers decide how to record
    that."""
    if not settings.google_drive_folder_id:
        raise DriveNotConfigured("Google Drive 目标文件夹 ID 未配置（GOOGLE_DRIVE_FOLDER_ID）")

    from googleapiclient.http import MediaFileUpload

    service = _service()
    file_metadata = {"name": drive_filename, "parents": [settings.google_drive_folder_id]}
    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=False)
    created = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    return created["id"]


def delete_file(file_id: str) -> None:
    """Best-effort delete of a Drive file by id. Raises if not configured or
    the API call fails — callers decide whether that should block their own
    operation (for daily photos it must not: the local delete always
    proceeds regardless of Drive's cooperation)."""
    if not settings.google_drive_folder_id:
        raise DriveNotConfigured("Google Drive 目标文件夹 ID 未配置（GOOGLE_DRIVE_FOLDER_ID）")

    service = _service()
    service.files().delete(fileId=file_id).execute()
