"""告警规则评估。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.alerts.notify import send_apprise
from app.config import AppConfig
from app.state import get_cpu_high_since, set_cpu_high_since
from app.storage.sqlite_store import Store

log = logging.getLogger(__name__)


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _cooled(store: Store, fingerprint: str, cooldown_sec: int) -> bool:
    last = store.last_alert_ts(fingerprint)
    if not last:
        return False
    try:
        delta = (datetime.now(timezone.utc) - _parse_ts(last)).total_seconds()
        return delta < cooldown_sec
    except Exception:
        return False


def _emit(
    store: Store,
    cfg: AppConfig,
    rule_id: str,
    severity: str,
    title: str,
    message: str,
    fingerprint: str,
    cooldown: int | None = None,
) -> None:
    cd = cooldown if cooldown is not None else cfg.alerts.cooldown_default_sec
    if _cooled(store, fingerprint, cd):
        return
    notified = send_apprise(cfg.alerts.apprise_urls, title, message)
    store.insert_alert(rule_id, severity, title, message, fingerprint, notified)
    log.info("alert %s notified=%s: %s", rule_id, notified, message)


def evaluate(store: Store, cfg: AppConfig, snapshot: dict[str, Any]) -> None:
    if not cfg.alerts.enabled:
        return
    rules = cfg.alerts.rules
    host = snapshot.get("host") or {}
    ts = snapshot.get("ts") or datetime.now(timezone.utc).isoformat()

    # 磁盘容量
    for fs in snapshot.get("filesystems") or []:
        pct = float(fs.get("used_pct") or 0)
        mid = fs.get("id") or fs.get("mount")
        mount = fs.get("mount")
        if pct >= rules.fs_used_crit_pct:
            _emit(
                store,
                cfg,
                "fs_used_crit",
                "critical",
                "磁盘使用率紧急",
                f"{mount} 使用率 {pct}%",
                f"fs_used_crit:{mid}",
                cooldown=1800,
            )
        elif pct >= rules.fs_used_warn_pct:
            _emit(
                store,
                cfg,
                "fs_used_warn",
                "warning",
                "磁盘使用率偏高",
                f"{mount} 使用率 {pct}%",
                f"fs_used_warn:{mid}",
            )

    # CPU 持续过高
    cpu = float(host.get("cpu_pct") or 0)
    if cpu >= rules.cpu_high_pct:
        since = get_cpu_high_since()
        if since is None:
            set_cpu_high_since(ts)
        else:
            try:
                dur = (_parse_ts(ts) - _parse_ts(since)).total_seconds()
            except Exception:
                dur = 0
            if dur >= rules.cpu_high_duration_sec:
                _emit(
                    store,
                    cfg,
                    "cpu_high",
                    "warning",
                    "CPU 持续过高",
                    f"CPU {cpu}% 已持续约 {int(dur)} 秒",
                    "cpu_high",
                )
    else:
        set_cpu_high_since(None)

    mem = float(host.get("mem_used_pct") or 0)
    if mem >= rules.mem_used_warn_pct:
        _emit(
            store,
            cfg,
            "mem_low",
            "warning",
            "内存使用率偏高",
            f"内存使用率 {mem}%",
            "mem_low",
        )

    temps = host.get("temps_c") or {}
    cpu_t = temps.get("cpu")
    if cpu_t is not None and float(cpu_t) >= rules.temp_cpu_warn_c:
        _emit(
            store,
            cfg,
            "temp_cpu_high",
            "warning",
            "CPU 温度过高",
            f"CPU 温度 {cpu_t}°C",
            "temp_cpu_high",
        )

    # SMART
    for d in snapshot.get("disks_smart_summary") or []:
        if d.get("skipped_standby"):
            continue
        did = d.get("id")
        if d.get("healthy") is False:
            _emit(
                store,
                cfg,
                "smart_unhealthy",
                "critical",
                "磁盘 SMART 异常",
                f"磁盘 {did} SMART 未通过",
                f"smart_unhealthy:{did}",
                cooldown=43200,
            )
        # 关键属性
        for a in d.get("attrs") or []:
            if a.get("name") in ("Reallocated_Sector_Ct", "Current_Pending_Sector", "Offline_Uncorrectable"):
                try:
                    raw = int(str(a.get("raw") or "0").split()[0])
                except Exception:
                    raw = 0
                if raw > 0:
                    _emit(
                        store,
                        cfg,
                        "smart_unhealthy",
                        "critical",
                        "磁盘坏道相关计数增长",
                        f"磁盘 {did} {a.get('name')}={raw}",
                        f"smart_attr:{did}:{a.get('name')}",
                        cooldown=43200,
                    )
        temp = d.get("temp_c")
        if temp is not None and float(temp) >= cfg.smart.temp_warn_c:
            _emit(
                store,
                cfg,
                "smart_temp_high",
                "warning",
                "磁盘温度过高",
                f"磁盘 {did} 温度 {temp}°C",
                f"smart_temp:{did}",
            )

    # Docker
    watch = cfg.docker.watch_containers
    for c in snapshot.get("containers") or []:
        name = c.get("name") or ""
        state = (c.get("state") or "").lower()
        if watch and name not in watch:
            continue
        if watch:
            # 仅监视名单
            if state != "running":
                _emit(
                    store,
                    cfg,
                    "docker_exited",
                    "critical",
                    "关注容器未运行",
                    f"容器 {name} 状态={state}",
                    f"docker_exited:{name}",
                    cooldown=1800,
                )
        else:
            # 空名单：对 exited 告警（可能吵，家用可配名单）
            if state in ("exited", "dead"):
                _emit(
                    store,
                    cfg,
                    "docker_exited",
                    "critical",
                    "容器已退出",
                    f"容器 {name} 状态={state}",
                    f"docker_exited:{name}",
                    cooldown=1800,
                )
