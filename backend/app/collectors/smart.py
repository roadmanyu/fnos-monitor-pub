"""SMART 采集（smartctl）；无工具时 mock。"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def discover_devices(configured: list[str] | None = None) -> list[str]:
    if configured:
        return list(configured)
    found: list[str] = []
    dev = Path("/dev")
    if not dev.is_dir():
        return found
    found.extend(sorted(str(p) for p in dev.glob("sd?")))
    found.extend(sorted(str(p) for p in dev.glob("nvme*n1")))
    return found


def collect_smart(
    devices: list[str] | None = None,
    skip_standby: bool = True,
    mock_on_failure: bool = True,
) -> list[dict[str, Any]]:
    if not shutil.which("smartctl"):
        log.info("smartctl not found; mock=%s", mock_on_failure)
        return [_mock_disk()] if mock_on_failure else []

    devs = discover_devices(devices)
    if not devs:
        return [_mock_disk()] if mock_on_failure else []

    results = []
    for dev in devs:
        try:
            results.append(_smart_one(dev, skip_standby=skip_standby))
        except Exception as e:
            log.warning("SMART %s failed: %s", dev, e)
    if not results and mock_on_failure:
        return [_mock_disk()]
    return results


def _smart_one(dev: str, skip_standby: bool) -> dict[str, Any]:
    disk_id = Path(dev).name
    # 检查 standby
    if skip_standby:
        chk = _run_smartctl(["-n", "standby", "-i", dev])
        # smartctl 返回 2 常表示 standby
        if chk.returncode in (2,) or "STANDBY" in (chk.stdout + chk.stderr).upper():
            return {
                "id": disk_id,
                "device": dev,
                "model": "",
                "healthy": None,
                "temp_c": None,
                "power_on_hours": None,
                "skipped_standby": True,
                "attrs": [],
            }

    info = _run_smartctl(["-i", "-H", "-A", "-j", dev])
    data: dict[str, Any] = {}
    try:
        data = json.loads(info.stdout or "{}")
    except json.JSONDecodeError:
        data = {}

    model = (
        data.get("model_name")
        or data.get("scsi_model_name")
        or ((data.get("model_family") or "") + "")
    )
    healthy = None
    st = data.get("smart_status") or {}
    if "passed" in st:
        healthy = bool(st["passed"])

    temp = None
    temp_obj = data.get("temperature") or {}
    if isinstance(temp_obj, dict) and "current" in temp_obj:
        temp = temp_obj["current"]

    poh = None
    attrs_out = []
    table = (data.get("ata_smart_attributes") or {}).get("table") or []
    for row in table:
        name = row.get("name") or ""
        raw = row.get("raw", {})
        raw_val = raw.get("value") if isinstance(raw, dict) else raw
        attrs_out.append(
            {
                "id": row.get("id"),
                "name": name,
                "raw": str(raw_val),
                "worst": row.get("worst"),
            }
        )
        if name == "Temperature_Celsius" and temp is None:
            try:
                temp = int(str(raw_val).split()[0])
            except Exception:
                pass
        if name == "Power_On_Hours":
            try:
                poh = int(str(raw_val).split()[0])
            except Exception:
                pass

    nvme = data.get("nvme_smart_health_information_log") or {}
    if poh is None and "power_on_hours" in nvme:
        poh = nvme.get("power_on_hours")
    if temp is None and "temperature" in nvme:
        temp = nvme.get("temperature")

    return {
        "id": disk_id,
        "device": dev,
        "model": model or "",
        "healthy": healthy if healthy is not None else True,
        "temp_c": temp,
        "power_on_hours": poh,
        "skipped_standby": False,
        "attrs": attrs_out,
    }


def _run_smartctl(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["smartctl", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


def _mock_disk() -> dict[str, Any]:
    return {
        "id": "sda",
        "device": "/dev/sda",
        "model": "MOCK-DISK",
        "healthy": True,
        "temp_c": 34,
        "power_on_hours": 1000,
        "skipped_standby": False,
        "attrs": [
            {"id": 5, "name": "Reallocated_Sector_Ct", "raw": "0", "worst": 100},
            {"id": 187, "name": "Reported_Uncorrect", "raw": "0", "worst": 100},
        ],
        "mock": True,
    }
