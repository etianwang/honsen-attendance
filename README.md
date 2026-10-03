# 埃塞俄比亚考勤系统

Web 版考勤登记系统，给埃塞俄比亚项目部用，替代 Excel 手工登记。班组长按半天批量登记组员的工地/请假/加班情况，管理员看全局统计和工地人工报表；每个人有基本信息+头像，每天可以上传多张合照（上班/下班/加班等，不限类型，最多10张）防止代打卡，合照会同步到腾讯云 COS 存档。

## 本地开发环境

1. 启动一个本地 PostgreSQL（用 Docker 最简单）：
   ```bash
   docker run -d --name honsen-attendance-pg \
     -e POSTGRES_USER=attendance -e POSTGRES_PASSWORD=attendance -e POSTGRES_DB=attendance \
     -p 5433:5432 postgres:16-alpine
   ```
   注意：本机 5432 端口已经被一个已有的 PostgreSQL 服务占用，所以这里映射到了 **5433**。

2. 建虚拟环境、装依赖：
   ```bash
   python -m venv .venv
   ./.venv/Scripts/python.exe -m pip install -r requirements.txt
   ```

3. 复制 `.env.example` 为 `.env`（默认已经指向 5433 端口的本地库，一般不用改；Google Drive 那两行先留空也没关系，看下面第 6 节）。

4. 建表：
   ```bash
   ./.venv/Scripts/python.exe -m alembic upgrade head
   ```

5. 种子数据 —— 埃塞俄比亚是全新起步，不导入旧数据，只建 1 个班组（埃塞酒店团队）+ 1 个工地（万豪酒店）+ 通用的请假/出差等可选值 + 1 个管理员 + 1 个班组长账号：
   ```bash
   ./.venv/Scripts/python.exe -m seed.seed_ethiopia
   ```
   会在终端打印新建的账号和临时密码，**请分发后自行修改**。员工名单为空，登录后到"花名册"页面手动添加组员。

   （`seed/seed_from_excel.py` 是给科特迪瓦那批历史数据用的旧脚本，埃塞俄比亚用不上，留着以后要是有别的国家/项目部要导入 Excel 花名册可以参考。）

6. 启动：
   ```bash
   ./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8010
   ```
   注意：本机 8000 端口被另一个已有服务占用，这里用了 **8010**。

7. 跑测试：
   ```bash
   docker exec honsen-attendance-pg psql -U attendance -d postgres -c "CREATE DATABASE attendance_test;"
   ./.venv/Scripts/python.exe -m pytest tests/ -v
   ```

## 配置腾讯云 COS（每日合照存档，当前使用中）

每天的班组合照会先稳妥地存在服务器本地（`uploads/daily_photos/`），**不管有没有配置 COS 都不会丢**；配置好下面四项后，新上传的合照会自动尝试同步一份到 COS，之前"待同步"的照片也能在合照那一栏点"重试同步"补传。上传前照片会先压缩（最长边 1920 像素、JPEG 质量 82%），既不占太多云存储空间，也保证看得清人脸。

1. 腾讯云控制台建一个 COS 存储桶（Bucket），记下桶名（形如 `你的桶名-APPID`）和地域（比如 `eu-frankfurt`、`ap-guangzhou`）。
2. 「访问管理」→「API 密钥管理」拿到 SecretId / SecretKey（建议单独建一个只有这个桶读写权限的子账号密钥，不要用主账号密钥）。
3. 把这四项填进 `.env`：
   ```
   COS_SECRET_ID=你的SecretId
   COS_SECRET_KEY=你的SecretKey
   COS_BUCKET=你的桶名-APPID
   COS_REGION=你的地域
   ```
4. 重启一下服务（`uvicorn`）让新的环境变量生效，上传一张合照试试，应该会看到"已同步到云端"。

## 配置 Google Drive（备选方案，当前未使用）

如果不想用 COS，也可以换成 Google Drive；`app/services/cos_service.py` 和 `app/services/gdrive_service.py` 接口一致，改 `app/services/daily_photo_service.py` 里的 import 换掉即可切换。

**重要**：如果是普通个人 Gmail 账号（不是付费的 Google Workspace 企业账号），**不能用"服务账号"（Service Account）这条路**——服务账号自己没有存储配额，只能往"共享云端硬盘"（Shared Drive）里写文件，而共享云端硬盘是 Workspace 才有的功能。个人账号必须走下面这套"用你自己的 Google 账号登录授权"的方式：

1. **建一个 Google Cloud 项目**（如果还没有）：打开 https://console.cloud.google.com ，右上角项目选择器 → 新建项目，随便起个名字，比如 `honsen-attendance`。

2. **开启 Google Drive API**：左侧菜单「API 和服务」→「库」，搜索 "Google Drive API"，点进去点「启用」。

3. **建 OAuth 客户端**（注意不是服务账号）：「API 和服务」→「凭据」→「创建凭据」→「OAuth 客户端 ID」。如果是第一次建，会先要求配置"OAuth 同意屏幕"——用户类型选「外部」，应用名称随便填，测试阶段把自己的 Gmail 加到"测试用户"里就行，不需要提交审核。应用类型选 **「桌面应用」（Desktop app）**，名字随意，创建后下载它的 JSON 文件。这个文件不含私钥泄露风险那么高，但也不要提交到代码仓库，放到 `secrets/gdrive-oauth-client.json`。

4. **在 Google Drive 里建一个文件夹专门存合照**，比如叫"埃塞俄比亚考勤合照"（这是你自己的账号自己的文件夹，不需要分享给任何人）。

5. **拿到文件夹 ID**：打开这个文件夹，浏览器地址栏最后一段就是文件夹 ID（`https://drive.google.com/drive/folders/`**`这一串`**）。

6. 把这几项填进 `.env`：
   ```
   GOOGLE_DRIVE_OAUTH_CLIENT_SECRET_PATH=E:/Project/Honsen-Attendance/secrets/gdrive-oauth-client.json
   GOOGLE_DRIVE_OAUTH_TOKEN_PATH=E:/Project/Honsen-Attendance/secrets/gdrive-token.json
   GOOGLE_DRIVE_FOLDER_ID=上一步拿到的文件夹ID
   ```

7. **跑一次一次性授权脚本**（会打开浏览器，让你用自己的 Google 账号登录并同意访问 Drive）：
   ```
   .venv/Scripts/python.exe scripts/gdrive_oauth_setup.py
   ```
   登录同意之后，授权信息（含刷新令牌）会存到上面配置的 `GOOGLE_DRIVE_OAUTH_TOKEN_PATH`，之后服务器每次上传/删除合照都复用这份授权，不需要再登录一次。

8. 重启一下服务（`uvicorn`）让新的环境变量生效，上传一张合照试试，应该会看到"已同步到 Google Drive"。

## 上线到生产 Postgres

把 `.env` 里的 `DATABASE_URL` 换成生产库的连接字符串，跑一次 `alembic upgrade head` 建表即可，代码不需要改。生产部署（选哪个云 Postgres、怎么托管这个 Web 应用）留给后续步骤决定。

## 目录结构

- `app/` — FastAPI 应用（models / routers / services / templates / static）
- `seed/seed_cameroon.py` — 喀麦隆全新起步用的种子脚本（1班组+1工地，不导入旧数据）
- `seed/seed_ethiopia.py` — 埃塞俄比亚全新起步用的种子脚本（1班组+1工地，不导入旧数据）
- `seed/seed_from_excel.py` — 旧的科特迪瓦 Excel 花名册导入脚本，喀麦隆不需要
- `uploads/` — 头像和每日合照的本地存储目录（`avatars/`、`daily_photos/`），不要提交到代码仓库
- `alembic/` — 数据库迁移
- `tests/` — pytest 测试（统计规则、花名册复制、权限隔离）
- `科特迪瓦考勤登记表2026.xlsx` — 科特迪瓦旧的 Excel 考勤表，作为历史存档保留
- `merge_attendance.py` — 早期一个不同方案（导出JSON合并回Excel）的脚本，新系统已不再使用这条路径
