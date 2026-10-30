"""采集主循环。"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.alerts.rules import evaluate
from app.collectors import disk as disk_col
from app.collectors import docker_col
from app.collectors import host as host_col
from app.collectors import smart as smart_col
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
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        # 启动立即采一轮
        while True:
            try:
                await asyncio.to_thread(self._collect_once)
            except Exception as e:
                log.exception("collect loop error: %s", e)
            await asyncio.sleep(self.cfg.collect.interval_sec)

    def _collect_once(self) -> None:
        import time

        cfg = self.cfg
        mock = cfg.collect.mock_on_failure
        ts = _utc_now()
        self._tick += 1

        host = host_col.collect_host(mock_on_failure=mock)
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
        if cfg.smart.enabled and (
            not self._smart_cache
            or now_m - self._last_smart_mono >= cfg.smart.interval_sec
        ):
            smart_list = smart_col.collect_smart(
                devices=cfg.smart.devices or None,
                skip_standby=cfg.smart.skip_standby,
                mock_on_failure=mock,
            )
            self._smart_cache = [
                {
                    "id": d.get("id"),
                    "model": d.get("model"),
                    "healthy": d.get("healthy"),
                    "temp_c": d.get("temp_c"),
                    "power_on_hours": d.get("power_on_hours"),
                    "skipped_standby": d.get("skipped_standby"),
                    "mock": d.get("mock", False),
                }
                for d in smart_list
            ]
            self._full_smart = {d["id"]: d for d in smart_list if d.get("id")}
            self._last_smart_mono = now_m

        snapshot = {
            "ts": ts,
            "host": {k: v for k, v in host.items() if k != "mock"},
            "host_mock": bool(host.get("mock")),
            "filesystems": filesystems,
            "disks_smart_summary": self._smart_cache,
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
        # 告警用精简快照（含 containers）
        evaluate(self.store, cfg, snapshot)
        log.debug("collected at %s", ts)

    def get_smart_detail(self, disk_id: str) -> dict | None:
        return self._full_smart.get(disk_id)
