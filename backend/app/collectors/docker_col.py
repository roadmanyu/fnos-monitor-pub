"""Docker 容器列表与基础 stats。"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def collect_containers(mock_on_failure: bool = True) -> list[dict[str, Any]]:
    try:
        import docker

        client = docker.from_env()
        out = []
        for c in client.containers.list(all=True):
            stats = {}
            cpu_pct = None
            mem_usage = None
            mem_limit = None
            if c.status == "running":
                try:
                    stats = c.stats(stream=False)
                    cpu_pct = _cpu_percent(stats)
                    mem = stats.get("memory_stats") or {}
                    mem_usage = mem.get("usage")
                    mem_limit = mem.get("limit") or 0
                except Exception as e:
                    log.debug("stats %s: %s", c.name, e)
            out.append(
                {
                    "id": c.short_id,
                    "name": c.name,
                    "image": (
                        c.image.tags[0]
                        if c.image.tags
                        else (c.image.short_id if c.image else "")
                    ),
                    "state": c.status,
                    "status": (c.attrs.get("State") or {}).get("Status")
                    or c.status,
                    "restart_count": (c.attrs.get("RestartCount") or 0),
                    "cpu_pct": cpu_pct,
                    "mem_usage_bytes": mem_usage,
                    "mem_limit_bytes": mem_limit or 0,
                }
            )
        return out
    except Exception as e:
        log.info("docker collect failed: %s (mock=%s)", e, mock_on_failure)
        if mock_on_failure:
            return [
                {
                    "id": "mock01",
                    "name": "jellyfin",
                    "image": "jellyfin/jellyfin:latest",
                    "state": "running",
                    "status": "running",
                    "restart_count": 0,
                    "cpu_pct": 1.2,
                    "mem_usage_bytes": 300 * 1024**2,
                    "mem_limit_bytes": 0,
                    "mock": True,
                },
                {
                    "id": "mock02",
                    "name": "stopped-demo",
                    "image": "busybox:latest",
                    "state": "exited",
                    "status": "exited",
                    "restart_count": 1,
                    "cpu_pct": None,
                    "mem_usage_bytes": None,
                    "mem_limit_bytes": 0,
                    "mock": True,
                },
            ]
        return []


def _cpu_percent(stats: dict) -> float | None:
    try:
        cpu = stats["cpu_stats"]
        precpu = stats["precpu_stats"]
        cpu_delta = cpu["cpu_usage"]["total_usage"] - precpu["cpu_usage"]["total_usage"]
        system_delta = cpu.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)
        online = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage") or [1])
        if system_delta > 0 and cpu_delta >= 0:
            return round((cpu_delta / system_delta) * online * 100.0, 2)
    except Exception:
        return None
    return None
