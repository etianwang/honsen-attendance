# Honsen 考勤系统

Web 版考勤登记系统，供各国家及项目部独立部署使用，替代 Excel 手工登记。班组长按半天批量登记组员的工地/请假/加班情况，管理员看全局统计和工地人工报表；每个人有基本信息+头像，每天可以上传多张合照（上班/下班/加班等，不限类型，最多10张）防止代打卡，合照会同步到腾讯云 COS 存档。

管理员可在「设置 → 账号」创建“审计/统计（只读）”账号，供老板或人事查看全局统计、下载统计报表、查看员工花名册、每日上工情况和合照。该账号不绑定班组，不能录入、上传、管理账号或修改业务数据，只能修改自己的密码。

## 本地开发环境

1. 启动一个本地 PostgreSQL（用 Docker 最简单）：
   ```bash
   docker run -d --name honsen-attendance-pg \
     -e POSTGRES_USER=attendance -e POSTGRES_PASSWORD=attendance -e POSTGRES_DB=attendance \
     -p 5432:5432 postgres:16-alpine
   ```
   如果本机 5432 已被占用，可改成 `-p 5433:5432`，并把 `.env` 的端口也改成 5433。

2. 建虚拟环境、装依赖：
   ```bash
   python -m venv .venv
   ./.venv/Scripts/python.exe -m pip install -r requirements.txt
   ```

3. 复制 `.env.example` 为 `.env`（默认指向本机 PostgreSQL 的 5432 端口；可选云存储配置可暂时留空，详见下方存储配置说明）。

4. 建表：
   ```bash
   ./.venv/Scripts/python.exe -m alembic upgrade head
   ```

5. 初始化业务数据：从 `seed/` 选择当前部署对应的国家初始化脚本，执行 `python -m seed.<脚本模块名>`。脚本创建班组、工地、通用考勤选项和初始账号，具体配置以对应脚本为准。

   新建账号和随机初始密码会在终端显示，请妥善分发并修改密码。全新初始化不导入员工，登录后在花名册页面添加。历史 Excel 导入脚本单独使用，详见下方 seed 说明。

6. 启动：
   ```bash
   ./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8010
   ```
   端口可按部署环境调整，以下统一使用 **8010**。

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

## 搬迁与备份

管理员可在「设置 → 迁移备份」下载完整的 PostgreSQL `.dump` 备份。备份包含考勤、账号和 COS 文件对象键，但**不会**包含 `.env` 中的密码或 COS 密钥。下载按钮所在的服务器需安装 PostgreSQL 客户端工具 `pg_dump`。

迁移到新服务器后，在新系统的「设置 → 迁移备份」选择该 `.dump` 文件，输入“恢复”确认，系统会自动导入并更新表结构，无需执行数据库命令。

将原服务器 `.env` 的 `COS_SECRET_ID`、`COS_SECRET_KEY`、`COS_BUCKET` 和 `COS_REGION` 安全地复制到新服务器；数据库里已有的 COS 对象键会继续指向同一批云端合照。头像未同步 COS，另行复制 `uploads/avatars/`。若有尚未同步到 COS 的每日合照，也复制 `uploads/daily_photos/`。新服务器同样要安装 PostgreSQL 客户端工具（`pg_dump`、`pg_restore`），供系统后台完成导入导出。

## 配置 Google Drive（备选方案，当前未使用）

如果不想用 COS，也可以换成 Google Drive；`app/services/cos_service.py` 和 `app/services/gdrive_service.py` 接口一致，改 `app/services/daily_photo_service.py` 里的 import 换掉即可切换。

**重要**：如果是普通个人 Gmail 账号（不是付费的 Google Workspace 企业账号），**不能用"服务账号"（Service Account）这条路**——服务账号自己没有存储配额，只能往"共享云端硬盘"（Shared Drive）里写文件，而共享云端硬盘是 Workspace 才有的功能。个人账号必须走下面这套"用你自己的 Google 账号登录授权"的方式：

1. **建一个 Google Cloud 项目**（如果还没有）：打开 https://console.cloud.google.com ，右上角项目选择器 → 新建项目，随便起个名字，比如 `honsen-attendance`。

2. **开启 Google Drive API**：左侧菜单「API 和服务」→「库」，搜索 "Google Drive API"，点进去点「启用」。

3. **建 OAuth 客户端**（注意不是服务账号）：「API 和服务」→「凭据」→「创建凭据」→「OAuth 客户端 ID」。如果是第一次建，会先要求配置"OAuth 同意屏幕"——用户类型选「外部」，应用名称随便填，测试阶段把自己的 Gmail 加到"测试用户"里就行，不需要提交审核。应用类型选 **「桌面应用」（Desktop app）**，名字随意，创建后下载它的 JSON 文件。这个文件不含私钥泄露风险那么高，但也不要提交到代码仓库，放到 `secrets/gdrive-oauth-client.json`。

4. **在 Google Drive 里建一个文件夹专门存合照**，按项目名称命名（这是你自己的账号自己的文件夹，不需要分享给任何人）。

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

## Ubuntu 生产部署

以下流程适用于 Ubuntu 服务器上的 `/www/wwwroot/honsen-attendance`。同一服务器部署多个项目时，**每个项目必须使用独立数据库**，并分别配置应用目录、端口和上传目录。

1. 安装 PostgreSQL、Git 和 Python 虚拟环境支持：
   ```bash
   apt update
   apt install -y postgresql git python3-venv
   systemctl enable --now postgresql
   ```

2. 创建应用数据库和账号。已有 `attendance` 账号时跳过第一条：
   ```bash
   sudo -u postgres psql
   ```
   ```sql
   CREATE USER attendance WITH PASSWORD '换成强密码';
   CREATE DATABASE attendance OWNER attendance;
   \q
   ```

3. 拉取代码并安装依赖：
   ```bash
   cd /www/wwwroot
   git clone https://github.com/etianwang/honsen-attendance.git honsen-attendance
   cd honsen-attendance
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

4. 创建生产配置：
   ```bash
   cp .env.example .env
   nano .env
   ```
   至少修改为：
   ```env
   DATABASE_URL=postgresql+psycopg://attendance:换成强密码@127.0.0.1:5432/attendance
   SECRET_KEY=换成随机长字符串
   UPLOAD_DIR=uploads
   ```
   如需每日合照同步到腾讯云 COS，再填写 `COS_SECRET_ID`、`COS_SECRET_KEY`、`COS_BUCKET` 和 `COS_REGION`。

5. 初始化表结构和业务数据：
   ```bash
   .venv/bin/python -m alembic upgrade head
   ```
   然后选择当前部署对应的 seed，通过 `.venv/bin/python -m seed.<脚本模块名>` 初始化业务数据。账号和工地配置以脚本为准，初始密码在终端显示。

6. 临时启动验证：
   ```bash
   .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
   ```
   生产环境应由 systemd 或服务器面板守护该命令，并通过 Nginx/Caddy 反向代理到 8010；PostgreSQL 的 5432 端口只保留本机访问，不要开放到公网。

7. 后续更新：
   ```bash
   cd /www/wwwroot/honsen-attendance
   git pull --ff-only
   .venv/bin/pip install -r requirements.txt
   .venv/bin/python -m alembic upgrade head
   ```
   若 Git 提示 `dubious ownership`，确认目录确实是本项目后执行一次：
   ```bash
   git config --global --add safe.directory /www/wwwroot/honsen-attendance
   ```
   最后重启应用服务。

## 虚拟环境配置与启动排查

虚拟环境需在实际部署目录创建，不随 Git 分发，也不要从其他服务器复制。Ubuntu 上先将路径替换为实际项目目录，再执行：

```bash
cd /你的项目部署目录
ls requirements.txt app/main.py
sudo apt update
sudo apt install -y python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python --version
```

若 `ls` 提示文件不存在，先确认代码已拉取到当前目录。后续安装依赖、数据库迁移和启动应用均使用该目录下的 `.venv/bin/python`，无需先激活虚拟环境。

若日志出现 `nohup: failed to run command '…/.venv/bin/python': No such file or directory`，检查启动配置中的项目路径，并在该目录按上述步骤创建虚拟环境、安装依赖。首次部署还需配置 `.env`、初始化数据库并选择对应 seed。

在项目目录中可临时后台启动验证：

```bash
nohup .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8010 > app.log 2>&1 &
tail -n 50 app.log
```

生产环境使用 systemd 或服务器面板管理进程，工作目录设为实际项目目录，启动命令中的 Python 路径指向该目录的 `.venv/bin/python`。避免同时运行多个使用相同端口的应用进程。

## 目录结构

- `app/` — FastAPI 应用（models / routers / services / templates / static）
- `seed/` — 按国家命名的初始化脚本及历史 Excel 导入脚本
- `uploads/` — 头像和每日合照的本地存储目录（`avatars/`、`daily_photos/`），不要提交到代码仓库
- `alembic/` — 数据库迁移
- `tests/` — pytest 测试（统计规则、花名册复制、权限隔离）
- `merge_attendance.py` — 早期一个不同方案（导出JSON合并回Excel）的脚本，新系统已不再使用这条路径

## seed 管理

每个国家或项目部署使用独立数据库，建表后选择对应初始化脚本。seed 文件统一按以下规则命名：

- `seed_<国家英文标识>.py`：全新部署初始化，定义班组、项目工地、通用考勤选项和初始账号。
- `seed_<国家英文标识>_from_excel.py`：历史 Excel 数据导入，按工作簿恢复班组、员工和月度花名册。

全新初始化使用 `python -m seed.<脚本模块名>`；历史导入还需提供 `--excel`、`--year`、`--month`。可通过 `--help` 查看所选脚本的参数。全新初始化脚本支持管理员及班组长的账号、密码参数，历史导入脚本支持管理员账号、密码参数。

现有 seed 遇到同名班组、考勤选项和账号会跳过，不会重置密码或删除数据。修改脚本后重新运行可以补充新增项，但不会自动重命名、修改或移除已有项。新增国家时应创建独立脚本，保持国家标识一致，并检查班组、工地和账号配置。

seed 用于初始化业务数据；表结构变更统一通过 Alembic 迁移管理。已有生产数据的部署在更新前应先备份，并确认所选脚本与目标数据库对应。
