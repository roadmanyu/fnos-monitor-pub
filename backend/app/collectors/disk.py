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
                    "fstype": p.fstype or "",
                    "total_bytes": int(u.total),
                    "used_bytes": int(u.used),
                    "used_pct": round(u.percent, 2),
                }
            )
        if not result and mock_on_failure:
            return _mock_filesystems()
        return result
    except Exception as e:
        log.warning("fs collect failed: %s", e)
        if mock_on_failure:
            return _mock_filesystems()
        raise


def _mount_id(mp: str) -> str:
    s = mp.strip("/").replace("/", "_") or "root"
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", s)[:64]


def _mock_filesystems() -> list[dict[str, Any]]:
    specs = [
        ("/", "ext4", 64 * 1024**3, 0.40),
        ("/vol1", "ext4", 18 * 1024**4, 0.48),
        ("/vol2", "btrfs", 48 * 1024**3, 0.13),
        ("/vol3", "ext4", 120 * 1024**3, 0.73),
    ]
    rows = []
    for mount, fstype, total, ratio in specs:
        rows.append({
            "id": _mount_id(mount),
            "mount": mount,
            "device": "/dev/mock",
            "fstype": fstype,
            "total_bytes": total,
            "used_bytes": int(total * ratio),
            "used_pct": round(ratio * 100, 2),
            "mock": True,
        })
    return rows
