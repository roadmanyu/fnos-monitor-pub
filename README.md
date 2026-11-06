# 飞牛 OS（fnOS）家用 NAS 监控

局域网里的一屏仪表盘：**采集 → SQLite → FastAPI `/api/v1` → Vue 3 PWA**。

桌面端（宽度 ≥ 1200px）一屏看完一台 NAS，页面不纵向滚动。顶行是系统、资源、趋势、网络，其下是 CPU、风扇、Docker、存储池和硬盘。手机改为单列，可以滚动。多台 NAS 由浏览器分别登录，在顶栏切换；每台自己采集，不在一台机器上代采另一台。顶栏可以按间隔自动轮播已登录的节点，副屏可以进全屏。点按或按键会暂停，空闲后再继续。

外观可以跟随系统，也可以固定浅色或深色，选择记在这台浏览器里。设置页按认证、节点、采集、告警、展示校准、高级分栏。高级里可以改 SMART 周期、硬盘插拔去抖和分级刷新，写入本机数据库，不必改只读的 `config.yaml`。

告警经 Apprise（Telegram、企业微信 / 钉钉 / 飞书 Webhook、邮件、通用 Webhook；不含 Bark）。SMART 磁盘健康包含在内。

功能、配置项、接口、多 NAS、升级和限制见 [项目说明.md](项目说明.md)。

## 默认账号

- 用户名：`admin`
- 密码：`admin123`（部署后立刻改 `config.yaml` 的 `password_hash`）

```bash
backend/.venv/bin/python scripts/hash_password.py '你的新密码'
```

把输出写入 `auth.password_hash`，并更换 `auth.jwt_secret`，然后重启。

## 在飞牛 NAS 上部署

1. 开启 SSH 与 Docker。
2. 把本仓库放到 NAS（例如 `/vol1/1000/fnos-monitor`）。
3. `cp config.example.yaml config.yaml`，修改 `jwt_secret`、密码哈希，按需填写 `alerts.apprise_urls`。
4. 构建并启动：

```bash
docker compose up -d --build
```

5. 浏览器打开 `http://<NAS局域网IP>:8787`。

已有安装从 `main` 升级（保留旁边的 `config.yaml` 和数据卷 `monitor-data`）：

```bash
git pull origin main
docker compose up -d --build
```

不要执行 `docker compose down -v`，否则会删掉数据库卷。

添加第二台：两台都各自跑这份监控。在已打开的页面里点顶栏 **添加**，或打开设置的 **节点**。二维码和「复制连接串」给出的是根地址（例如 `http://192.168.1.8:8787`，不要带 `/api`）。用那台自己的账号登录。令牌只留在这台浏览器里，请求直接发到对方，不经过当前这台代理。

权限：

- 只读挂载 `/var/run/docker.sock` 以列出容器。
- `privileged: true` 便于 SMART 和风扇调速。
- 不要把 8787 映射到公网。

## 本地开发

无 Docker / `smartctl` / docker.sock 时，`collect.mock_on_failure: true`（默认）会填入模拟磁盘、SMART 和容器。主机 CPU、内存、交换和网卡吞吐仍尽量采真实值。界面会标「模拟数据」。

```bash
cp config.example.yaml config.yaml
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd ..
MONITOR_DATA_DIR=./data MONITOR_CONFIG=./config.yaml \
  backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8787
```

另开终端：

```bash
cd web && npm install && npm run dev
# http://127.0.0.1:5173
```

冒烟：

```bash
./scripts/smoke_check.sh http://127.0.0.1:8787
```

## 目录

```
backend/   FastAPI + 采集 + 告警
web/       Vue 3 PWA
mobile/    原生 App 占位
scripts/   密码哈希、冒烟脚本
```
