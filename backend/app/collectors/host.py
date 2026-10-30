"""主机 CPU/内存/交换/负载/温度/网卡吞吐。"""
from __future__ import annotations

import logging
import time
from typing import Any

import psutil

log = logging.getLogger(__name__)

# 上一轮计数器，用于把累计字节换成每秒速率。首轮速率为 None。
_net_prev: dict[str, float | None] = {"mono": None, "sent": None, "recv": None}
_disk_prev: dict[str, float | None] = {"mono": None, "read": None, "write": None}


def collect_host(mock_on_failure: bool = True) -> dict[str, Any]:
    try:
        per = psutil.cpu_percent(interval=0.3, percpu=True) or []
        cpu = round(sum(per) / len(per), 2) if per else round(psutil.cpu_percent(interval=None), 2)
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        try:
            load1, load5, _load15 = psutil.getloadavg()
        except (AttributeError, OSError):
            load1 = load5 = 0.0
        temps = _read_temps()
        up_bps, down_bps = _net_rates()
        read_bps, write_bps = _disk_rates()
        try:
            uptime_sec = max(0, int(time.time() - psutil.boot_time()))
        except Exception:
            uptime_sec = None
        return {
            "cpu_pct": cpu,
            "cpu_cores": [round(float(x), 1) for x in per],
            "mem_total_bytes": int(mem.total),
            "mem_used_bytes": int(mem.used),
            "mem_used_pct": round(mem.percent, 2),
            "swap_total_bytes": int(swap.total),
            "swap_used_bytes": int(swap.used),
            "swap_used_pct": round(swap.percent, 2),
            "load1": round(load1, 2),
            "load5": round(load5, 2),
            "temps_c": temps,
            "uptime_sec": uptime_sec,
            "net_up_bps": None if up_bps is None else round(up_bps, 1),
            "net_down_bps": None if down_bps is None else round(down_bps, 1),
            "disk_read_bps": None if read_bps is None else round(read_bps, 1),
            "disk_write_bps": None if write_bps is None else round(write_bps, 1),
            "mock": False,
        }
    except Exception as e:
        log.warning("host collect failed: %s", e)
        if mock_on_failure:
            return _mock_host()
        raise


def _net_rates() -> tuple[float | None, float | None]:
    io = psutil.net_io_counters()
    if io is None:
        return None, None
    now = time.monotonic()
    up = down = None
    if _net_prev["mono"] is not None and _net_prev["sent"] is not None and _net_prev["recv"] is not None:
        dt = now - float(_net_prev["mono"])
        if dt > 0.2 and io.bytes_sent >= _net_prev["sent"] and io.bytes_recv >= _net_prev["recv"]:
            up = (io.bytes_sent - float(_net_prev["sent"])) / dt
            down = (io.bytes_recv - float(_net_prev["recv"])) / dt
    _net_prev["mono"] = now
    _net_prev["sent"] = float(io.bytes_sent)
    _net_prev["recv"] = float(io.bytes_recv)
    return up, down


def _disk_rates() -> tuple[float | None, float | None]:
    try:
        io = psutil.disk_io_counters()
    except Exception:
        return None, None
    if io is None:
        return None, None
    now = time.monotonic()
    read_bps = write_bps = None
    if _disk_prev["mono"] is not None and _disk_prev["read"] is not None and _disk_prev["write"] is not None:
        dt = now - float(_disk_prev["mono"])
        if dt > 0.2 and io.read_bytes >= _disk_prev["read"] and io.write_bytes >= _disk_prev["write"]:
            read_bps = (io.read_bytes - float(_disk_prev["read"])) / dt
            write_bps = (io.write_bytes - float(_disk_prev["write"])) / dt
    _disk_prev["mono"] = now
    _disk_prev["read"] = float(io.read_bytes)
    _disk_prev["write"] = float(io.write_bytes)
    return read_bps, write_bps


def _mock_host() -> dict[str, Any]:
    return {
        "cpu_pct": 8.5,
        "cpu_cores": [6.0, 11.0],
        "mem_total_bytes": 16 * 1024**3,
        "mem_used_bytes": 6 * 1024**3,
        "mem_used_pct": 37.5,
        "swap_total_bytes": 2 * 1024**3,
        "swap_used_bytes": int(2 * 1024**3 * 0.12),
        "swap_used_pct": 12.0,
        "load1": 0.2,
        "load5": 0.3,
        "temps_c": {"cpu": 42.0, "other": {}},
        "uptime_sec": 3600 * 24,
        "net_up_bps": 12_000.0,
        "net_down_bps": 80_000.0,
        "disk_read_bps": 0.0,
        "disk_write_bps": 40_000.0,
        "mock": True,
    }


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
