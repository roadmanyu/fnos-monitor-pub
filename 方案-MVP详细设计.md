# 飞牛 OS 监控 — MVP 详细设计

> 承接 `方案-整体设计.md`  
> 日期：2026-10-30（Asia/Shanghai）  
> 范围：可落地的第一期实现规格；确认后即可写代码

---

## 0. MVP 边界（已定）

| 项 | 决定 |
|----|------|
| 架构 | 路径 B：采集 → SQLite → FastAPI → Vue 3 PWA |
| 部署 | Docker Compose + SSH（飞牛 NAS） |
| 访问 | **仅局域网**；默认绑定 `0.0.0.0:8787`（或主机网络，见 Compose） |
| 认证 | 单用户 **用户名+密码 → JWT** |
| 采集 | CPU/内存/温度、磁盘容量、**SMART**、Docker 状态与基础 stats |
| 告警 | 规则引擎 + 历史；**Apprise** → Telegram、企业微信/钉钉/飞书 Webhook、邮件、通用 Webhook（**不含 Bark**） |
| 不做（MVP） | 原生 App、公网/穿透、多用户 RBAC、`.fpk`、非官方 fnOS WS 主路径、Grafana |

---

## 1. 模块边界

```
┌──────────────────────────────────────────────────────────┐
│  fnos-monitor（单 Compose 项目）                          │
│                                                          │
│  ┌─────────────┐    ┌──────────┐    ┌─────────────────┐ │
│  │ collectors  │───►│ storage  │◄───│ api (FastAPI)   │ │
│  │ 定时采集     │    │ SQLite   │    │ /api/v1 + 静态  │ │
│  └─────────────┘    └──────────┘    │ 托管 web/dist   │ │
│         │                ▲          └────────┬────────┘ │
│         ▼                │                   │          │
│  ┌─────────────┐         │                   │ 局域网    │
│  │ alerts      │─────────┘                   ▼          │
│  │ 规则评估     │──► Apprise ──► 外部通道      Vue PWA    │
│  └─────────────┘                                        │
└──────────────────────────────────────────────────────────┘
```

| 模块 | 职责 | 不负责 |
|------|------|--------|
| **collectors** | 读 `/proc`、filesystem、`smartctl`、Docker API；写入快照/时序表 | 不推送、不鉴权 |
| **storage** | SQLite schema、写入、查询、保留期清理 | 不感知 HTTP |
| **api** | JWT 鉴权、REST、可选 SSE、托管前端静态文件 | 不直接跑 `smartctl`（调 storage / 读最新快照） |
| **alerts** | 读最新指标评规则、写告警历史、调 Apprise | 不做复杂工作流引擎 |
| **web** | 登录、仪表盘、磁盘/Docker/告警/设置页 | 不直连 Docker/SMART |

**进程模型（MVP）：** 一个后端容器内 **采集循环 + FastAPI** 同进程（asyncio 后台 task），降低 Compose 复杂度。若日后拆分，storage 与配置文件不变。

---

## 2. 数据存储（SQLite）

路径：`/data/monitor.db`（Compose volume）。WAL 模式。

### 2.1 表（草图）

**`metric_points`** — 时序（按指标名降维，简单够用）

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | |
| ts | TEXT | ISO8601 UTC |
| metric | TEXT | 如 `cpu.pct` / `mem.used_pct` / `fs.used_pct./vol1` / `temp.cpu` |
| value | REAL | |
| labels_json | TEXT | 可选 JSON，如 `{"mount":"/vol1"}` |

索引：`(metric, ts)`。

**`snapshots`** — 整包最新/历史快照（便于 snapshot API，可每轮写一行）

| 列 | 类型 |
|----|------|
| ts | TEXT PK |
| payload_json | TEXT |

保留策略：只保留最近 N 条或 24h 内全量 + 更早抽样（MVP：**每轮覆盖写「latest」逻辑外，history 靠 metric_points**；`snapshots` 可仅存最新 1～2 行作缓存，或每轮插入并 7 天清理）。

**推荐 MVP 简化：**  
- 实时页读「内存中最后一次采集结果」+ 落库 `metric_points`  
- `snapshots` 表可选；若实现，TTL 与 points 同为 **7 天**

**`docker_samples`**

| 列 | 说明 |
|----|------|
| ts, container_id, name, state, restart_count, cpu_pct, mem_bytes | 每轮每个容器一行或只存最新状态表 |

MVP 可再简：Docker **状态以每次采集的当前列表为准**（API 实时读 Docker），历史仅对「关注容器」记 `state` 变更到告警；资源曲线第二期。**MVP 验收：列表实时正确即可，容器 CPU 曲线可选。**

**`alert_events`**

| 列 | 说明 |
|----|------|
| id, ts, rule_id, severity, title, message, fingerprint, notified, acked | fingerprint 用于冷却去重 |

**`alert_rules` / 通道：** MVP 规则与通道以 **YAML 配置为主**；API 提供只读或有限更新（见 §3）。用户改推送 URL 可改配置文件或设置页写回 YAML（设置页写回为加分项，MVP 可用「改 `config.yaml` 后重启」）。

---

## 3. API 端点与请求/响应草图

Base：`http://<NAS_LAN_IP>:8787/api/v1`  
Header：`Authorization: Bearer <jwt>`（除 login / health）  
时间：UTC ISO8601；Web 按 `Asia/Shanghai` 展示。

### 3.1 认证与元信息

**`POST /auth/login`**

```json
// req
{ "username": "admin", "password": "***" }
// 200
{ "access_token": "<jwt>", "token_type": "bearer", "expires_in": 86400 }
```

JWT 声明：`sub`=用户名，`exp`；密钥来自配置 `jwt_secret`。MVP 单用户，与配置中 `auth.username` / `auth.password_hash` 比对（bcrypt）。

**`GET /health`**（可匿名）

```json
{ "status": "ok", "api_version": "v1" }
```

**`GET /meta`**

```json
{
  "api_version": "v1",
  "app_version": "0.1.0",
  "hostname": "fnos-home",
  "last_collect_ts": "2026-10-30T09:41:00Z",
  "collect_interval_sec": 30,
  "timezone_display": "Asia/Shanghai"
}
```

### 3.2 指标

**`GET /metrics/snapshot`**

```json
{
  "ts": "2026-10-30T09:41:00Z",
  "host": {
    "cpu_pct": 12.5,
    "mem_total_bytes": 17179869184,
    "mem_used_bytes": 7200000000,
    "mem_used_pct": 41.9,
    "load1": 0.35,
    "load5": 0.40,
    "temps_c": { "cpu": 48.0, "other": {} }
  },
  "filesystems": [
    {
      "id": "vol1",
      "mount": "/vol1",
      "device": "/dev/mapper/...",
      "total_bytes": 8000111222333,
      "used_bytes": 5760000000000,
      "used_pct": 72.0
    }
  ],
  "disks_smart_summary": [
    {
      "id": "sda",
      "model": "TOSHIBA...",
      "healthy": true,
      "temp_c": 34,
      "power_on_hours": 12000,
      "skipped_standby": false
    }
  ],
  "docker": { "running": 5, "stopped": 1, "total": 6 }
}
```

**`GET /metrics/history?metric=cpu.pct&from=...&to=...&step=60`**

```json
{
  "metric": "cpu.pct",
  "step_sec": 60,
  "points": [
    { "ts": "2026-10-30T08:00:00Z", "value": 10.2 },
    { "ts": "2026-10-30T08:01:00Z", "value": 11.0 }
  ]
}
```

约定 `metric` 枚举（文档化）：`cpu.pct` | `mem.used_pct` | `load1` | `temp.cpu` | `fs.used_pct.<id>` | `disk.temp.<id>` 等。

### 3.3 磁盘 / SMART

**`GET /disks`** — 合并挂载容量 + SMART 摘要（同上列表结构）。

**`GET /disks/{id}/smart`**

```json
{
  "id": "sda",
  "healthy": true,
  "temp_c": 34,
  "attrs": [
    { "id": 5, "name": "Reallocated_Sector_Ct", "raw": "0", "worst": 100 },
    { "id": 187, "name": "Reported_Uncorrect", "raw": "0", "worst": 100 }
  ],
  "raw_updated_ts": "2026-10-30T09:30:00Z",
  "standby_skipped": false
}
```

### 3.4 Docker

**`GET /docker/containers`**

```json
{
  "containers": [
    {
      "id": "abc123",
      "name": "jellyfin",
      "image": "jellyfin/jellyfin:latest",
      "state": "running",
      "status": "Up 2 days",
      "restart_count": 0,
      "cpu_pct": 2.1,
      "mem_usage_bytes": 314572800,
      "mem_limit_bytes": 0
    }
  ]
}
```

### 3.5 告警

**`GET /alerts?limit=50&severity=`**

```json
{
  "items": [
    {
      "id": 1,
      "ts": "2026-10-30T09:00:00Z",
      "rule_id": "fs_used_high",
      "severity": "warning",
      "title": "磁盘使用率偏高",
      "message": "/vol1 使用率 86%",
      "notified": true,
      "acked": false
    }
  ]
}
```

**`POST /alerts/{id}/ack`** → `{ "ok": true }`

**`GET /alerts/rules`** — 返回当前生效规则（来自配置）。

**`GET /alerts/channels`** — 返回已配置通道类型与「是否已填密钥」（脱敏，不回传完整 webhook/密码）。

### 3.6 实时（可选加分，建议 MVP 做）

**`GET /stream`**（SSE，需 JWT：可用 `?token=` 仅作 EventSource 折中，或 cookie；**推荐**先用 Web **30s 轮询 snapshot**，SSE 作增强）

MVP **验收不强制 SSE**；Web 用 `setInterval` 拉 snapshot 即可。

### 3.7 错误形

```json
{ "code": "unauthorized", "message": "invalid credentials" }
```

HTTP：401 / 403 / 404 / 422 / 500。

---

## 4. Web 页面信息架构（Vue 3 PWA）

路由（需登录，除 `/login`）：

| 路由 | 页面 | 内容 |
|------|------|------|
| `/login` | 登录 | 用户名密码 → 存 JWT（memory + localStorage） |
| `/` | 概览 | 卡片：CPU/内存/负载/温度；磁盘使用 Top；Docker running/stopped；最近 3 条告警；小趋势（CPU/内存近 1h） |
| `/disks` | 磁盘 | 挂载容量表；SMART 健康灯、温度、通电时间；点开抽屉看属性 |
| `/docker` | 容器 | 列表筛选 running/all；状态色；重启次数；CPU/内存 |
| `/alerts` | 告警 | 历史列表、级别筛选、确认 ack；规则说明（只读） |
| `/settings` | 设置 | 展示采集周期、保留天数、通道是否已配置（脱敏）；改密码可二期；文档链接「如何改 config」 |
| 离线/错误 | — | API 不可达时友好提示（局域网断开） |

PWA：`manifest.webmanifest` + 图标；可「添加到主屏幕」。Service Worker：**仅缓存壳**，API 数据不长期离线伪造。

视觉：深色优先（NAS 场景）、大触控目标（手机局域网访问）。

---

## 5. 采集周期与 SMART 节流

| 采集项 | 周期 | 说明 |
|--------|------|------|
| CPU / 内存 / 负载 / 温度(sensors) | **2s** | 写入 `metric_points` |
| 文件系统容量 | **60s** | 可与 30s 同轮但每 2 次采一次 |
| Docker 列表 + stats | **2s** | `docker.sock`；stats 可对 running 容器采样 |
| **SMART** | **15min**（可配 `smart.interval_sec: 900`） | `smartctl --json`；**先** `powermode`/`--nocheck=standby`：若 standby 则 **跳过** 并标记 `skipped_standby`，不唤醒 |
| DB 清理 | 每天一次 | 删除 7 天前 `metric_points` / 旧告警（告警可留 30 天） |

**SMART 实现要点：**

- 设备发现：扫 `/dev/sd*` `/dev/nvme*n1`（可配置白名单 `smart.devices`）
- 超时单盘 10s；失败记日志，不中断整轮采集
- 容器需：`privileged: true` 或 `cap_add: [SYS_RAWIO]` + 设备映射；Compose 给 **profiles / 文档二选一**，默认给较宽松权限以便家用一次跑通，README 写明风险

**温度：** 优先 lm-sensors/hwmon；无则仅盘温来自 SMART；`temps_c.cpu` 缺失时前端显示「—」。

---

## 6. 告警规则默认值与通道

### 6.1 规则（默认开启）

| rule_id | 条件 | severity | 冷却 |
|---------|------|----------|------|
| `fs_used_warn` | 任一监控挂载 `used_pct ≥ 85` | warning | 60min |
| `fs_used_crit` | `used_pct ≥ 95` | critical | 30min |
| `cpu_high` | `cpu_pct ≥ 90` 持续 **10min**（连续采样） | warning | 60min |
| `mem_low` | `mem_used_pct ≥ 90`（即可用 &lt; ~10%） | warning | 60min |
| `temp_cpu_high` | `temp.cpu ≥ 85`（若有传感器） | warning | 60min |
| `smart_unhealthy` | SMART `healthy=false` 或关键 raw（重分配/待决）&gt;0 且增长 | critical | 12h |
| `smart_temp_high` | 盘温 `≥ 55°C` | warning | 60min |
| `docker_exited` | 配置的 `watch_containers` 中容器 state≠running | critical | 30min |

`fingerprint` = `rule_id + 对象键`（如 mount、disk id、container name），冷却期内同 fingerprint 不重复通知（仍可写一条 throttled 日志，不刷推送）。

### 6.2 Apprise 通道（已定）

配置里用 Apprise URL 列表，例如：

- Telegram：`tgram://bot_token/chat_id`
- 企业微信：`wxworkbot://token` 或官方 webhook 形态（以 Apprise 文档为准）
- 钉钉：`dingtalk://token?secret=`
- 飞书：`lark://token` / webhook
- 邮件：`mailto://user:pass@smtp:port?to=`
- 通用：`json://host/path` 或 `form://` 等 Apprise 支持的 webhook

**不含 Bark。** 未配置任何 URL 时：规则仍评估并写 `alert_events`，`notified=false`。

---

## 7. Compose 服务划分

```yaml
# 逻辑结构（落地时写完整文件）
services:
  monitor:
    build: ./backend   # 或 image
    container_name: fnos-monitor
    restart: unless-stopped
    ports:
      - "8787:8787"
    volumes:
      - ./config.yaml:/app/config.yaml:ro
      - monitor-data:/data
      - /var/run/docker.sock:/var/run/docker.sock:ro
      # SMART：按需
      # - /dev:/dev:ro
    environment:
      - TZ=Asia/Shanghai
    # 家用 SMART 简化权限（文档说明）：
    privileged: true   # 或改 cap_add+devices，见 README
    # 可选：pid: host 以改善主机指标；MVP 可先 privileged+sock 验证

volumes:
  monitor-data:
```

- **单服务** `monitor`：API + 采集 + 内置静态 Web（多阶段构建：先 `web` build，再拷进后端镜像 `app/static`）。
- 不强制独立 nginx；需要时用户可自行反代（MVP 不默认公网）。

**构建：** `Dockerfile` 多阶段 — Node 构建 `web/` → Python 镜像安装依赖并复制 `dist`。

---

## 8. 配置项示例

`config.example.yaml`：

```yaml
server:
  host: "0.0.0.0"
  port: 8787

auth:
  username: "admin"
  # 首次用脚本生成 bcrypt 填入；或环境变量 MONITOR_PASSWORD 启动时哈希写入
  password_hash: "$2b$12$..."
  jwt_secret: "change-me-to-long-random"
  jwt_expire_sec: 86400

collect:
  interval_sec: 2
  fs_interval_sec: 60
  retention_days: 7
  filesystem_mounts: []   # 空=自动发现，排除 tmpfs/overlay 等
  filesystem_exclude_prefixes:
    - "/proc"
    - "/sys"
    - "/run"
    - "/var/lib/docker"

smart:
  enabled: true
  interval_sec: 900
  devices: []             # 空=自动发现
  skip_standby: true
  temp_warn_c: 55

docker:
  enabled: true
  watch_containers: []    # 空=任意 exited 都告警；非空=仅名单

alerts:
  enabled: true
  cooldown_default_sec: 3600
  apprise_urls: []
  # 例:
  # - "tgram://BOT/CHAT"
  # - "mailto://user:pass@smtp.example.com:587?to=you@example.com"
  rules:
    fs_used_warn_pct: 85
    fs_used_crit_pct: 95
    cpu_high_pct: 90
    cpu_high_duration_sec: 600
    mem_used_warn_pct: 90
    temp_cpu_warn_c: 85

display:
  timezone: "Asia/Shanghai"
```

密钥：**不要**提交真实 `config.yaml`；可用环境变量覆盖 `jwt_secret`、`apprise_urls`。

---

## 9. 目录落地（与整体方案对齐）

```text
/workspace/fnos-monitor/
├── 方案-整体设计.md
├── 方案-MVP详细设计.md      # 本文
├── README.md
├── docker-compose.yml
├── config.example.yaml
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── collectors/
│   │   ├── storage/
│   │   ├── alerts/
│   │   ├── api/v1/
│   │   ├── schemas/
│   │   └── static/          # CI/构建填入 web dist
│   └── tests/
├── web/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
├── mobile/README.md         # 占位
└── scripts/
    ├── smoke_check.sh
    └── hash_password.py
```

---

## 10. 验收标准（MVP Done）

### 功能

1. Compose 在飞牛（或同构 Linux）上 `up` 后，局域网浏览器打开 `:8787` 见登录页。  
2. 正确账密登录拿到 JWT；错误密码 401。  
3. 概览页展示 CPU/内存（数值合理）；有传感器则显示温度。  
4. 磁盘页显示至少一处真实挂载容量；SMART：能列出磁盘，standby 盘显示跳过而非报死错。  
5. Docker 页列出容器，状态与 `docker ps` 一致（需挂载 sock）。  
6. 人为把测试规则阈值调低或模拟：产生告警历史；配置至少一条 Apprise URL 后能收到推送（Telegram **或** 邮件 **或** Webhook 任一即可验通）。  
7. 历史接口返回近时段 `cpu.pct` 折线，Web 概览可见。  
8. PWA manifest 可安装；刷新后 JWT 仍可用（未过期）。

### 非功能

9. 采集循环异常不导致 API 整体退出（记录错误，下一轮重试）。  
10. README 含：SSH 部署步骤、`docker.sock`、SMART 权限风险、仅局域网警告、配置样例。  
11. 无 Bark 相关代码与文档推荐。

### 明确不测（可后做）

- 公网 HTTPS、多用户、App 商店包、SSE 必达、容器历史曲线、改密 UI。

---

## 11. 建议实现顺序

1. 配置加载 + SQLite + 主机/磁盘容量采集  
2. FastAPI：login / meta / snapshot / history  
3. Docker 采集 + API  
4. SMART 节流采集 + API  
5. 告警规则 + Apprise + alerts API  
6. Vue 页面联调  
7. 多阶段 Dockerfile + Compose + smoke_check  
8. README 与验收自测清单打勾  

---

**本文即开工规格。** 下一步：按 §11 在 `/workspace/fnos-monitor` 创建骨架并实现。
