from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://attendance:attendance@127.0.0.1:5432/attendance"
    secret_key: str = "change-me-to-a-random-secret"

    upload_dir: str = "uploads"

    # Google Drive upload (daily team photos), authorized as the operator's
    # own personal Google account — a service account can't be used here: it
    # has zero storage quota of its own and can only write into a Shared
    # Drive, which requires a paid Google Workspace plan a personal Gmail
    # account doesn't have. See scripts/gdrive_oauth_setup.py for the
    # one-time interactive login that produces the token file. Kept for
    # reference/possible future use — the active backend is Tencent COS
    # below, which needs no interactive login at all.
    google_drive_oauth_client_secret_path: str | None = None
    google_drive_oauth_token_path: str = "secrets/gdrive-token.json"
    google_drive_folder_id: str | None = None

    # Tencent COS upload (daily team photos) — the active remote-storage
    # backend. A plain SecretId/SecretKey pair scoped to one bucket, no
    # OAuth/interactive login needed. Until all four are set, photos stay
    # local with a "pending" status and can be synced later without losing
    # anything.
    cos_secret_id: str | None = None
    cos_secret_key: str | None = None
    cos_bucket: str | None = None
    cos_region: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
