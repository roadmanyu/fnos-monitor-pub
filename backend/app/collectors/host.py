"""主机 CPU/内存/交换/负载/温度/网卡吞吐，以及系统身份。"""
from __future__ import annotations

import ipaddress
import logging
import platform
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any

import psutil

log = logging.getLogger(__name__)

# 上一轮计数器，用于把累计字节换成每秒速率。首轮速率为 None。
_net_prev: dict[str, float | None] = {"mono": None, "sent": None, "recv": None}
_disk_prev: dict[str, float | None] = {"mono": None, "read": None, "write": None}
_disk_peaks: deque[float] = deque(maxlen=30)
_rapl_prev: dict[str, tuple[float, int]] = {}


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
        disk_peak = _note_disk_peak(read_bps, write_bps)
        power_watts, power_source = _read_power()
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
            "disk_bps_peak": None if disk_peak is None else round(disk_peak, 1),
            "power_watts": power_watts,
            "power_source": power_source,
            **_identity(),
            "public_ipv4": _public_ipv4_cached(),
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


def _note_disk_peak(read_bps: float | None, write_bps: float | None) -> float | None:
    if read_bps is None and write_bps is None:
        return max(_disk_peaks) if _disk_peaks else None
    total = (read_bps or 0) + (write_bps or 0)
    _disk_peaks.append(total)
    return max(_disk_peaks)


def _read_power() -> tuple[float | None, str | None]:
    ipmi = _ipmi_power_watts()
    if ipmi is not None:
        return round(ipmi, 1), "ipmi"
    rapl = _rapl_power_watts()
    if rapl is not None:
        return round(rapl, 1), "rapl"
    return None, None


def _ipmi_power_watts() -> float | None:
    if not shutil.which("ipmitool"):
        return None
    try:
        result = subprocess.run(
            ["ipmitool", "dcmi", "power", "reading"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception as exc:
        log.info("ipmi power skipped: %s", exc)
        return None
    text = f"{result.stdout}\n{result.stderr}"
    match = re.search(r"Instantaneous power reading:\s*(\d+(?:\.\d+)?)", text, re.I)
    if not match:
        return None
    return float(match.group(1))


def _rapl_power_watts() -> float | None:
    root = Path("/sys/class/powercap")
    if not root.is_dir():
        return None
    domains: list[Path] = []
    for zone in root.glob("intel-rapl:*"):
        name_path = zone / "name"
        energy = zone / "energy_uj"
        if not energy.is_file():
            continue
        try:
            name = name_path.read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue
        if name.startswith("package") or name == "dram":
            domains.append(energy)
    if not domains:
        return None
    now = time.monotonic()
    total = 0.0
    got_delta = False
    for energy in domains:
        try:
            uj = int(energy.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        key = str(energy)
        prev = _rapl_prev.get(key)
        _rapl_prev[key] = (now, uj)
        if prev is None:
            continue
        dt = now - prev[0]
        delta = uj - prev[1]
        if dt <= 0.2 or delta < 0:
            continue
        total += (delta / 1_000_000.0) / dt
        got_delta = True
    if not got_delta:
        return None
    return total


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
        "disk_bps_peak": 40_000.0,
        "power_watts": None,
        "power_source": None,
        "os": "Linux",
        "arch": "x86_64",
        "cpu_model": "MOCK CPU",
        "lan_ipv4": "192.168.1.8",
        "public_ipv4": None,
        "gpu_model": None,
        "mock": True,
    }


_static_identity: dict[str, Any] | None = None
_gpu_done = False
_gpu_value: str | None = None
_public_lock = threading.Lock()
_public_cache: dict[str, Any] = {"ip": None, "fetched_at": 0.0, "busy": False}
_PUBLIC_OK_TTL = 600.0
_PUBLIC_FAIL_TTL = 60.0
_LSPCI_FIELDS = re.compile(r'"([^"]*)"')


def _identity() -> dict[str, Any]:
    global _static_identity
    if _static_identity is None:
        _static_identity = {
            "os": _os_pretty(),
            "arch": platform.machine() or None,
            "cpu_model": _cpu_model(),
            "gpu_model": _gpu_model(),
        }
    return {
        **_static_identity,
        "lan_ipv4": _lan_ipv4(),
    }


def _os_pretty() -> str | None:
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"') or None
    except Exception:
        pass
    name = f"{platform.system()} {platform.release()}".strip()
    return name or None


def _cpu_model() -> str | None:
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except Exception:
        text = ""
    for key in ("model name", "hardware", "model"):
        for line in text.splitlines():
            if line.lower().startswith(key + "\t") or line.lower().startswith(key + " "):
                value = line.split(":", 1)[-1].strip()
                if value:
                    return value
    proc = (platform.processor() or "").strip()
    return proc or None


def _lan_ipv4() -> str | None:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.2)
        try:
            sock.connect(("192.0.2.1", 9))
            ip = sock.getsockname()[0]
        finally:
            sock.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        for addrs in psutil.net_if_addrs().values():
            for addr in addrs:
                if addr.family != socket.AF_INET:
                    continue
                ip = addr.address or ""
                if ip.startswith("127.") or ip.startswith("169.254."):
                    continue
                return ip
    except Exception:
        return None
    return None


def _gpu_model() -> str | None:
    global _gpu_done, _gpu_value
    if not _gpu_done:
        _gpu_value = _probe_gpu()
        _gpu_done = True
    return _gpu_value


def _probe_gpu() -> str | None:
    if shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            for line in (result.stdout or "").splitlines():
                name = line.strip()
                if name and "not supported" not in name.lower():
                    return name
        except Exception:
            pass
    if shutil.which("lspci"):
        try:
            result = subprocess.run(
                ["lspci", "-mm"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            found = _gpu_from_lspci(result.stdout or "")
            if found:
                return found
        except Exception:
            pass
    return None


def _gpu_from_lspci(text: str) -> str | None:
    for line in text.splitlines():
        low = line.lower()
        if "vga" not in low and "3d controller" not in low and "display controller" not in low:
            continue
        parts = _LSPCI_FIELDS.findall(line)
        if len(parts) < 3:
            continue
        vendor, device = parts[1].strip(), parts[2].strip()
        if not device:
            continue
        if vendor and vendor.lower() not in device.lower():
            return f"{vendor} {device}"
        return device
    return None


def current_public_ipv4() -> str | None:
    """给 API 读取用：只看缓存并按需触发刷新，不等待网络。"""
    return _public_ipv4_cached()


def _public_ipv4_cached() -> str | None:
    """返回缓存。过期时在后台刷新，不占用采集线程。"""
    now = time.monotonic()
    with _public_lock:
        ip = _public_cache["ip"]
        age = now - float(_public_cache["fetched_at"] or 0)
        ttl = _PUBLIC_OK_TTL if ip else _PUBLIC_FAIL_TTL
        fresh = _public_cache["fetched_at"] and age < ttl
        if fresh or _public_cache["busy"]:
            return ip if isinstance(ip, str) else None
        _public_cache["busy"] = True
    threading.Thread(target=_fetch_public_ipv4, name="public-ip", daemon=True).start()
    return ip if isinstance(ip, str) else None


def _fetch_public_ipv4() -> None:
    ip = None
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "fnos-monitor"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                text = resp.read(64).decode("ascii", errors="ignore")
            parsed = _parse_ipv4(text)
            if parsed:
                ip = parsed
                break
        except Exception as exc:
            log.info("public ip %s skipped: %s", url, exc)
    with _public_lock:
        _public_cache["ip"] = ip
        _public_cache["fetched_at"] = time.monotonic()
        _public_cache["busy"] = False


def _parse_ipv4(text: str) -> str | None:
    token = (text or "").strip().split()
    if not token:
        return None
    try:
        return str(ipaddress.IPv4Address(token[0]))
    except Exception:
        return None


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
