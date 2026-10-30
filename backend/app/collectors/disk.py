"""文件系统容量。"""
from __future__ import annotations

import logging
import re
from typing import Any

import psutil

log = logging.getLogger(__name__)


def collect_filesystems(
    mounts: list[str] | None = None,
    exclude_prefixes: list[str] | None = None,
    mock_on_failure: bool = True,
) -> list[dict[str, Any]]:
    exclude_prefixes = exclude_prefixes or []
    try:
        parts = psutil.disk_partitions(all=False)
        result = []
        for p in parts:
            mp = p.mountpoint
            if mounts:
                if mp not in mounts:
                    continue
            else:
                if any(mp == pref or mp.startswith(pref.rstrip("/") + "/") or mp.startswith(pref)
                       for pref in exclude_prefixes):
                    continue
                # 跳过常见虚拟/容器挂载
                if p.fstype in ("tmpfs", "devtmpfs", "overlay", "squashfs", "proc", "sysfs", "cgroup", "cgroup2"):
                    continue
            try:
                u = psutil.disk_usage(mp)
            except PermissionError:
                continue
            fid = _mount_id(mp)
            result.append(
                {
                    "id": fid,
                    "mount": mp,
                    "device": p.device,
                    "total_bytes": int(u.total),
                    "used_bytes": int(u.used),
                    "used_pct": round(u.percent, 2),
                }
            )
        if not result and mock_on_failure:
            return [_mock_fs()]
        return result
    except Exception as e:
        log.warning("fs collect failed: %s", e)
        if mock_on_failure:
            return [_mock_fs()]
        raise


def _mount_id(mp: str) -> str:
    s = mp.strip("/").replace("/", "_") or "root"
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", s)[:64]


def _mock_fs() -> dict[str, Any]:
    return {
        "id": "vol1",
        "mount": "/vol1",
        "device": "/dev/mock",
        "total_bytes": 8 * 1024**4,
        "used_bytes": int(8 * 1024**4 * 0.42),
        "used_pct": 42.0,
        "mock": True,
    }
