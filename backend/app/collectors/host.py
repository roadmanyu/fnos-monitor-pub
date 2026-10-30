"""主机 CPU/内存/负载/温度。"""
from __future__ import annotations

import logging
from typing import Any

import psutil

log = logging.getLogger(__name__)


def collect_host(mock_on_failure: bool = True) -> dict[str, Any]:
    try:
        cpu = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        try:
            load1, load5, load15 = psutil.getloadavg()
        except (AttributeError, OSError):
            load1 = load5 = load15 = 0.0
        temps = _read_temps()
        return {
            "cpu_pct": round(cpu, 2),
            "mem_total_bytes": int(mem.total),
            "mem_used_bytes": int(mem.used),
            "mem_used_pct": round(mem.percent, 2),
            "load1": round(load1, 2),
            "load5": round(load5, 2),
            "temps_c": temps,
            "mock": False,
        }
    except Exception as e:
        log.warning("host collect failed: %s", e)
        if mock_on_failure:
            return {
                "cpu_pct": 8.5,
                "mem_total_bytes": 16 * 1024**3,
                "mem_used_bytes": 6 * 1024**3,
                "mem_used_pct": 37.5,
                "load1": 0.2,
                "load5": 0.3,
                "temps_c": {"cpu": 42.0, "other": {}},
                "mock": True,
            }
        raise


def _read_temps() -> dict[str, Any]:
    out: dict[str, Any] = {"cpu": None, "other": {}}
    try:
        sensors = psutil.sensors_temperatures(fahrenheit=False)
    except Exception:
        return out
    if not sensors:
        return out
    # 常见键：coretemp, k10temp, cpu_thermal, acpitz
    preferred = ("coretemp", "k10temp", "cpu_thermal", "acpitz", "cpu")
    cpu_val = None
    for name in preferred:
        if name in sensors and sensors[name]:
            entries = sensors[name]
            vals = [e.current for e in entries if e.current is not None]
            if vals:
                cpu_val = max(vals)
                break
    other = {}
    for name, entries in sensors.items():
        for e in entries:
            key = f"{name}.{e.label or 'temp'}"
            if e.current is not None:
                other[key] = round(e.current, 1)
    out["cpu"] = round(cpu_val, 1) if cpu_val is not None else None
    out["other"] = other
    return out
