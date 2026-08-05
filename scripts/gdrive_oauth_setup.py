"""一次性的交互式 Google 账号授权：会打开浏览器，让你用自己的 Google 账号登录
并同意访问 Drive，授权结果（含刷新令牌）会存到 GOOGLE_DRIVE_OAUTH_TOKEN_PATH
指定的文件里，之后服务器每次上传/删除合照都复用这个缓存的授权，不需要再登录。

跑之前先在 Google Cloud Console 建一个"桌面应用"（Desktop app）类型的 OAuth
客户端（不是服务账号），下载它的 JSON 文件，把路径填到 .env 的
GOOGLE_DRIVE_OAUTH_CLIENT_SECRET_PATH 里，具体步骤看 README。

用法：
    .venv/Scripts/python.exe scripts/gdrive_oauth_setup.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.gdrive_service import SCOPES  # noqa: E402


def main() -> None:
    if not settings.google_drive_oauth_client_secret_path:
        print("请先在 .env 里设置 GOOGLE_DRIVE_OAUTH_CLIENT_SECRET_PATH，指向下载的 OAuth 客户端 JSON 文件")
        return
    client_secret_path = Path(settings.google_drive_oauth_client_secret_path)
    if not client_secret_path.exists():
        print(f"找不到这个文件：{client_secret_path}")
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path = Path(settings.google_drive_oauth_token_path)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"授权成功，已保存到 {token_path}")
    print("现在可以重启服务，上传合照会自动同步到 Drive 了。")


if __name__ == "__main__":
    main()
