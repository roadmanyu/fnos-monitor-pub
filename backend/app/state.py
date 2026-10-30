"""进程内最新采集快照。"""
from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_latest: dict[str, Any] = {}
_cpu_high_since: str | None = None


def set_latest(payload: dict[str, Any]) -> None:
    global _latest
    with _lock:
        _latest = payload


def get_latest() -> dict[str, Any]:
    with _lock:
        return dict(_latest) if _latest else {}


def get_cpu_high_since() -> str | None:
    return _cpu_high_since


def set_cpu_high_since(ts: str | None) -> None:
    global _cpu_high_since
    _cpu_high_since = ts
