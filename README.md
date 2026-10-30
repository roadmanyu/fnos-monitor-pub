# 飞牛 OS（fnOS）家用 NAS 监控 — MVP

轻量自研：**采集 → SQLite → FastAPI `/api/v1` → Vue 3 PWA**。  
面向个人/家里飞牛 NAS，**仅局域网**。告警经 Apprise（Telegram、企业微信/钉钉/飞书 Webhook、邮件、通用 Webhook；**不含 Bark**）。

设计文档：`方案-整体设计.md`、`方案-MVP详细设计.md`。

## 默认账号

- 用户名：`admin`
- 密码：`admin123`（请立刻改 `config.yaml` 中的 `password_hash`）

生成哈希：

```bash
backend/.venv/bin/python scripts/hash_password.py '你的新密码'
```

## 飞牛 NAS 上 Docker Compose 部署（推荐）

1. 开启 SSH 与 Docker。  
2. 把本目录拷到 NAS（如 `/vol1/1000/fnos-monitor`）。  
3. `cp config.example.yaml config.yaml`，改 `jwt_secret`、密码哈希、可选 `alerts.apprise_urls`。  
4. 构建并启动：

```bash
docker compose up -d --build
```

5. 浏览器访问：`http://<NAS局域网IP>:8787`

权限说明：

- 挂载 `/var/run/docker.sock:ro` 以列出容器。  
- `privileged: true` 便于 SMART（可改为 `cap_add: [SYS_RAWIO]` + 设备映射，见详设）。  
- **不要**把 8787 映射到公网。

## 开发机本地运行（无真实 NAS）

无 Docker / 无 smartctl / 无 docker.sock 时，配置项 `collect.mock_on_failure: true`（默认）会返回**模拟**磁盘、SMART、容器数据，主机 CPU/内存仍尽量采真实值。界面 meta 会标「模拟数据」。

```bash
# 后端
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd ..
MONITOR_DATA_DIR=./data MONITOR_CONFIG=./config.yaml \
  backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8787

# 另开终端：前端开发（代理到 8787）
cd web && npm install && npm run dev
# 打开 http://127.0.0.1:5173
```

或先构建前端再由后端托管：

```bash
cd web && npm install && npm run build
mkdir -p backend/app/static && cp -r dist/* backend/app/static/
# 再启动 uvicorn（同上）
```

冒烟：

```bash
./scripts/smoke_check.sh http://127.0.0.1:8787
```

## Apprise 通道示例

在 `config.yaml`：

```yaml
alerts:
  apprise_urls:
    - "tgram://BOT_TOKEN/CHAT_ID"
    - "mailto://user:pass@smtp.example.com:587?to=you@example.com"
    # 企微/钉钉/飞书/通用 Webhook 见 Apprise 文档
```

改完重启服务。未配置 URL 时仍会写入告警历史，只是不推送。

## 目录

```
backend/   FastAPI + 采集 + 告警
web/       Vue 3 PWA
mobile/    App 占位
scripts/   密码哈希、冒烟脚本
```

## 已知限制

- MVP 单用户；通道/规则以 YAML 为主，设置页只读展示。  
- 容器资源历史曲线、SSE、公网 HTTPS、原生 App 未做。  
- SMART 依赖宿主机 `smartctl` 与设备权限；standby 盘会跳过以免唤醒。  
- 开发机 mock 的 exited 容器可能触发 `docker_exited` 告警（有冷却）。

## 本仓库验证说明

- 开发环境若 **8787 已被占用**，可改端口，例如 `--port 8765`，冒烟：`./scripts/smoke_check.sh http://127.0.0.1:8765`。
- 无 `docker.sock` / `smartctl` 时 `mock_on_failure: true` 会注入模拟容器与 SMART；`GET /api/v1/meta` 的 `mock_mode` 为 `true`。
- 本机未跑通 `docker compose up` 时，请以 NAS 上 Compose 为准；镜像构建见 `backend/Dockerfile`（多阶段含前端）。
