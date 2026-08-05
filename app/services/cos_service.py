"""Tencent COS upload for daily team photos. Unlike Google Drive (personal
Gmail accounts need an interactive OAuth login, service accounts have no
storage quota of their own), COS just needs a plain SecretId/SecretKey pair
scoped to one bucket — a proper server-to-server credential model with no
login step, which is what a headless server actually wants.

Photos are always saved to local disk first (see file_storage.py) — this
module is only responsible for best-effort syncing that local copy onward to
COS. A failure here never loses the photo; it just leaves the row's
drive_status as 'pending'/'failed' for a later retry."""

from pathlib import Path

from app.config import settings


class CosNotConfigured(Exception):
    pass


def is_configured() -> bool:
    return bool(settings.cos_secret_id and settings.cos_secret_key and settings.cos_bucket and settings.cos_region)


def _client():
    from qcloud_cos import CosConfig, CosS3Client

    config = CosConfig(Region=settings.cos_region, SecretId=settings.cos_secret_id, SecretKey=settings.cos_secret_key)
    return CosS3Client(config)


def upload_file(local_path: Path, object_key: str, mime_type: str = "image/jpeg") -> str:
    """Uploads local_path to the configured bucket under object_key. Returns
    object_key itself — COS has no separate file-id concept the way Drive
    does; the key is the durable reference used later to delete it."""
    if not is_configured():
        raise CosNotConfigured("腾讯云 COS 未配置（SecretId / SecretKey / Bucket / Region）")
    client = _client()
    client.upload_file(Bucket=settings.cos_bucket, LocalFilePath=str(local_path), Key=object_key)
    return object_key


def delete_file(object_key: str) -> None:
    """Best-effort delete of an object from COS by key. Raises if not
    configured or the API call fails — callers decide whether that should
    block their own operation (for daily photos it must not: the local
    delete always proceeds regardless of COS's cooperation)."""
    if not is_configured():
        raise CosNotConfigured("腾讯云 COS 未配置（SecretId / SecretKey / Bucket / Region）")
    client = _client()
    client.delete_object(Bucket=settings.cos_bucket, Key=object_key)
