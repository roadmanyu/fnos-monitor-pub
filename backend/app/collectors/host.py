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
        temps, core_temps = _temperature_bundle(len(per))
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
            "cpu_cores": _build_cpu_cores(per, core_temps),
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
        "cpu_pct": 9.7,
        "cpu_cores": [
            {"pct": 20.0, "freq_mhz": 800, "freq_max_mhz": 3400, "temp_c": 36.0},
            {"pct": 8.0, "freq_mhz": 800, "freq_max_mhz": 3400, "temp_c": 37.0},
            {"pct": 5.0, "freq_mhz": 831, "freq_max_mhz": 3400, "temp_c": 35.0},
            {"pct": 6.0, "freq_mhz": 800, "freq_max_mhz": 3400, "temp_c": 35.0},
            {"pct": 11.0, "freq_mhz": 814, "freq_max_mhz": 3400, "temp_c": 37.0},
            {"pct": 8.0, "freq_mhz": 800, "freq_max_mhz": 3400, "temp_c": 35.0},
        ],
        "mem_total_bytes": 16 * 1024**3,
        "mem_used_bytes": 6 * 1024**3,
        "mem_used_pct": 37.5,
        "swap_total_bytes": 2 * 1024**3,
        "swap_used_bytes": int(2 * 1024**3 * 0.12),
        "swap_used_pct": 12.0,
        "load1": 0.2,
        "load5": 0.3,
        "temps_c": {"cpu": 37.0, "other": {"nvme.Composite": 41.0}},
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


_CORE_TEMP_RE = re.compile(r"(?:core|cpu)\s*(\d+)\b", re.I)
_PKG_TEMP_RE = re.compile(r"package|tctl|tdie|composite", re.I)
_CORE_SENSOR_NAMES = ("coretemp", "k10temp", "cpu_thermal", "cpu-thermal", "acpitz", "cpu")


def _sensor_rows() -> list[tuple[str, str, float]]:
    try:
        sensors = psutil.sensors_temperatures(fahrenheit=False) or {}
    except Exception:
        return []
    rows: list[tuple[str, str, float]] = []
    for name, entries in sensors.items():
        for entry in entries or []:
            if entry.current is None:
                continue
            rows.append((str(name), (entry.label or "").strip(), round(float(entry.current), 1)))
    return rows


def _temperature_bundle(n: int) -> tuple[dict[str, Any], list[float | None]]:
    """整机温度、其它传感器，以及按 Core N 映射的每核温度。对不上的核为 None。"""
    rows = _sensor_rows()
    core_temps: list[float | None] = [None] * n
    used: set[int] = set()
    for i, (_name, label, val) in enumerate(rows):
        match = _CORE_TEMP_RE.search(label)
        if not match:
            continue
        idx = int(match.group(1))
        if 0 <= idx < n and core_temps[idx] is None:
            core_temps[idx] = val
            used.add(i)
    if n and all(v is None for v in core_temps):
        candidates = [
            (i, val)
            for i, (name, label, val) in enumerate(rows)
            if name.lower() in _CORE_SENSOR_NAMES
            and not _PKG_TEMP_RE.search(label)
            and not _CORE_TEMP_RE.search(label)
        ]
        if len(candidates) == n:
            for slot, (i, val) in enumerate(candidates):
                core_temps[slot] = val
                used.add(i)
    by_name: dict[str, list[float]] = {}
    for name, _label, val in rows:
        by_name.setdefault(name, []).append(val)
    cpu_val = None
    for name in _CORE_SENSOR_NAMES:
        if by_name.get(name):
            cpu_val = max(by_name[name])
            break
    other: dict[str, float] = {}
    for i, (name, label, val) in enumerate(rows):
        if i in used:
            continue
        other[f"{name}.{label or 'temp'}"] = val
    temps = {"cpu": None if cpu_val is None else round(float(cpu_val), 1), "other": other}
    return temps, core_temps


def _freq_value(raw: float | None) -> int | None:
    if raw is None:
        return None
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return int(round(n))


def _read_freqs(n: int) -> tuple[list[int | None], list[int | None]]:
    currents: list[int | None] = [None] * n
    maxes: list[int | None] = [None] * n
    per = None
    try:
        per = psutil.cpu_freq(percpu=True)
    except Exception:
        per = None
    if per:
        for i in range(min(n, len(per))):
            item = per[i]
            if not item:
                continue
            currents[i] = _freq_value(item.current)
            maxes[i] = _freq_value(item.max)
        if any(v is not None for v in currents):
            return currents, maxes
    one = None
    try:
        one = psutil.cpu_freq(percpu=False)
    except Exception:
        one = None
    if one and n:
        cur = _freq_value(one.current)
        mx = _freq_value(one.max)
        return [cur] * n, [mx] * n
    return currents, maxes


def _build_cpu_cores(per: list[float], core_temps: list[float | None]) -> list[dict[str, Any]]:
    n = len(per)
    currents, maxes = _read_freqs(n)
    cores = []
    for i, pct in enumerate(per):
        cores.append({
            "pct": round(float(pct), 1),
            "freq_mhz": currents[i] if i < len(currents) else None,
            "freq_max_mhz": maxes[i] if i < len(maxes) else None,
            "temp_c": core_temps[i] if i < len(core_temps) else None,
        })
    return cores
