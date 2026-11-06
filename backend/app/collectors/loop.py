"""采集主循环。"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.alerts.rules import evaluate
from app.calibration import apply_disk_calibration, visible_disks
from app.collectors import disk as disk_col
from app.collectors import docker_col
from app.collectors import fans as fan_col
from app.collectors import host as host_col
from app.collectors import smart as smart_col
from app.collectors.presence import DiskPresenceDebounce
from app.config import AppConfig
from app.state import set_latest
from app.storage.sqlite_store import Store

log = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class CollectorLoop:
    def __init__(self, cfg: AppConfig, store: Store):
        self.cfg = cfg
        self.store = store
        self._tick = 0
        self._last_smart_mono = 0.0
        self._smart_cache: list[dict[str, Any]] = []
        self._full_smart: dict[str, dict] = {}
        self._presence = DiskPresenceDebounce()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        # 启动立即采一轮
        while True:
            started = time.monotonic()
            try:
                await asyncio.to_thread(self._collect_once)
            except Exception as e:
                log.exception("collect loop error: %s", e)
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(0.0, self.cfg.collect.interval_sec - elapsed))

    def _collect_once(self) -> None:
        import time

        cfg = self.cfg
        mock = cfg.collect.mock_on_failure
        ts = _utc_now()
        self._tick += 1

        host = host_col.collect_host(mock_on_failure=mock)
        fan_state = fan_col.collect_fans(
            mock_on_failure=mock,
            force_mock=bool(host.get("mock")),
        )
        filesystems: list[dict] = []
        if self._tick == 1 or (self._tick * cfg.collect.interval_sec) % max(
            cfg.collect.fs_interval_sec, cfg.collect.interval_sec
        ) < cfg.collect.interval_sec:
            filesystems = disk_col.collect_filesystems(
                mounts=cfg.collect.filesystem_mounts or None,
                exclude_prefixes=cfg.collect.filesystem_exclude_prefixes,
                mock_on_failure=mock,
            )
        else:
            prev = __import__("app.state", fromlist=["get_latest"]).get_latest()
            filesystems = list(prev.get("filesystems") or [])

        containers = []
        if cfg.docker.enabled:
            containers = docker_col.collect_containers(mock_on_failure=mock)

        now_m = time.monotonic()
        if cfg.smart.enabled and self._smart_due(cfg, now_m):
            smart_list = smart_col.collect_smart(
                devices=cfg.smart.devices or None,
                skip_standby=cfg.smart.skip_standby,
                mock_on_failure=mock,
            )
            self._smart_cache = [
                {
                    "id": d.get("id"),
                    "model": d.get("model"),
                    "serial": d.get("serial") or "",
                    "wwn": d.get("wwn") or "",
                    "identity_key": d.get("identity_key"),
                    "identity_stable": d.get("identity_stable"),
                    "healthy": d.get("healthy"),
                    "temp_c": d.get("temp_c"),
                    "power_on_hours": d.get("power_on_hours"),
                    "capacity_bytes": d.get("capacity_bytes"),
                    "label_bytes": d.get("label_bytes"),
                    "media": d.get("media"),
                    "skipped_standby": d.get("skipped_standby"),
                    "mock": d.get("mock", False),
                }
                for d in smart_list
            ]
            self._full_smart = {d["id"]: d for d in smart_list if d.get("id")}
            self._last_smart_mono = now_m

        raw_disks = [dict(item) for item in self._smart_cache]
        disk_col.annotate_disk_roles(raw_disks, filesystems)
        disks_raw = [dict(item) for item in raw_disks]
        calibrated = apply_disk_calibration(raw_disks, self.store.list_disk_calibrations())
        visible = visible_disks(calibrated)
        snapshot = {
            "ts": ts,
            "host": {k: v for k, v in host.items() if k != "mock"},
            "host_mock": bool(host.get("mock")),
            "filesystems": filesystems,
            "disks_smart_summary": visible,
            "_disks_raw": disks_raw,
            "containers": containers,
            "docker": {
                "running": sum(1 for c in containers if (c.get("state") or "").lower() == "running"),
                "stopped": sum(
                    1
                    for c in containers
                    if (c.get("state") or "").lower() not in ("running",)
                ),
                "total": len(containers),
            },
            "fans": fan_state.get("fans") or [],
            "control": fan_state.get("control") or "off",
            "reason": fan_state.get("reason") or "",
        }
        # 附带完整 SMART 供 API
        snapshot["_smart_full"] = self._full_smart

        points = [
            (ts, "cpu.pct", float(host["cpu_pct"]), None),
            (ts, "mem.used_pct", float(host["mem_used_pct"]), None),
            (ts, "load1", float(host["load1"]), None),
        ]
        if host.get("temps_c", {}).get("cpu") is not None:
            points.append((ts, "temp.cpu", float(host["temps_c"]["cpu"]), None))
        if host.get("swap_used_pct") is not None:
            points.append((ts, "swap.used_pct", float(host["swap_used_pct"]), None))
        if host.get("net_up_bps") is not None:
            points.append((ts, "net.up_bps", float(host["net_up_bps"]), None))
        if host.get("net_down_bps") is not None:
            points.append((ts, "net.down_bps", float(host["net_down_bps"]), None))
        for fs in filesystems:
            points.append(
                (
                    ts,
                    f"fs.used_pct.{fs['id']}",
                    float(fs["used_pct"]),
                    {"mount": fs["mount"]},
                )
            )
        for d in self._smart_cache:
            if d.get("temp_c") is not None:
                points.append((ts, f"disk.temp.{d['id']}", float(d["temp_c"]), None))

        self.store.insert_points(points)
        if self._tick % 120 == 0:
            self.store.cleanup(cfg.collect.retention_days)

        set_latest(snapshot)
        # 隐藏只影响展示。告警仍看全部磁盘，避免藏起一块坏盘就不再通知。
        alert_view = dict(snapshot)
        alert_view["disks_smart_summary"] = calibrated
        evaluate(self.store, cfg, alert_view)
        log.debug("collected at %s", ts)

    def _smart_due(self, cfg: AppConfig, now_m: float) -> bool:
        """盘符没变时按 SMART 周期采集；插拔去抖窗口内不读盘。"""
        from pathlib import Path

        paths = smart_col.discover_devices(cfg.smart.devices or None)
        ids = [Path(path).name for path in paths if Path(path).name]
        if not ids and cfg.collect.mock_on_failure:
            ids = ["sda"]
        action = self._presence.consider(ids, now_m, float(cfg.collect.disk_plug_debounce_sec))
        if action == "pending":
            return False
        if action == "accept":
            return True
        return (not self._smart_cache) or (
            now_m - self._last_smart_mono >= cfg.smart.interval_sec
        )

    def get_smart_detail(self, disk_id: str) -> dict | None:
        return self._full_smart.get(disk_id)
