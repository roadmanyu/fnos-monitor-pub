"""风扇转速读取与 PWM 调速。

转速来自 hwmon（与 psutil.sensors_fans 同一套 sysfs）。
写 PWM 只接受本进程扫描到的 hwmon 编号，不接受客户端传入的路径。
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import psutil

from app.config import get_config

log = logging.getLogger(__name__)

HWMON_ROOT = Path("/sys/class/hwmon")
READBACK_SEC = 2.0
PWM_TOLERANCE = 2
_ID_RE = re.compile(r"^hwmon(\d+):fan(\d+)$")
_LOCK = threading.Lock()
# id -> 服务器自己发现的节点。不进入 API 响应。
_PATHS: dict[str, dict[str, Path | None]] = {}
# 读回失败后本进程内不再写这些风扇。
_FORCED_READONLY: dict[str, str] = {}


class FanRejected(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _display_label(raw: str, index: int) -> str:
    text = (raw or "").strip()
    low = text.lower()
    if "cpu" in low or "processor" in low:
        return "CPU"
    if any(key in low for key in ("chassis", "case", "sys", "system")):
        return "机箱"
    return text or f"风扇{index}"


def _read_int(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
        return int(float(text))
    except (OSError, ValueError):
        return None


def _mode_from_enable(value: int | None) -> str:
    if value == 1:
        return "manual"
    if value in (2, 5):
        return "auto"
    return "unknown"


def _percent(pwm: int | None) -> int | None:
    if pwm is None:
        return None
    return int(round(max(0, min(255, pwm)) * 100 / 255))


def _pwm_from_percent(percent: int) -> int:
    return int(round(max(0, min(100, percent)) * 255 / 100))


def _writable(path: Path | None) -> bool:
    return bool(path and path.is_file() and os.access(path, os.W_OK))


def _scan() -> list[dict[str, Any]]:
    """扫描 hwmon。psutil.sensors_fans 作为补充：sysfs 扫不到但 psutil 有数时只读展示。"""
    found: list[dict[str, Any]] = []
    paths: dict[str, dict[str, Path | None]] = {}
    root = HWMON_ROOT
    if root.is_dir():
        for hw in sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("hwmon")):
            chip = ""
            name_file = hw / "name"
            if name_file.is_file():
                try:
                    chip = name_file.read_text(encoding="utf-8").strip()
                except OSError:
                    chip = ""
            for fan_file in sorted(hw.glob("fan*_input")):
                match = re.fullmatch(r"fan(\d+)_input", fan_file.name)
                if not match:
                    continue
                index = int(match.group(1))
                rpm = _read_int(fan_file)
                if rpm is None:
                    continue
                label_file = hw / f"fan{index}_label"
                raw_label = ""
                if label_file.is_file():
                    try:
                        raw_label = label_file.read_text(encoding="utf-8").strip()
                    except OSError:
                        raw_label = ""
                pwm_path = hw / f"pwm{index}"
                enable_path = hw / f"pwm{index}_enable"
                if not pwm_path.is_file():
                    pwm_path = None
                if not enable_path.is_file():
                    enable_path = None
                pwm = _read_int(pwm_path) if pwm_path else None
                enable = _read_int(enable_path) if enable_path else None
                fan_id = f"{hw.name}:fan{index}"
                controllable = _writable(pwm_path) and _writable(enable_path)
                found.append({
                    "id": fan_id,
                    "chip": chip or hw.name,
                    "label": _display_label(raw_label, index),
                    "rpm": rpm,
                    "pwm": pwm,
                    "pwm_percent": _percent(pwm),
                    "mode": _mode_from_enable(enable),
                    "controllable": controllable,
                })
                paths[fan_id] = {"pwm": pwm_path, "enable": enable_path}
    if not found:
        found.extend(_from_psutil())
    with _LOCK:
        _PATHS.clear()
        _PATHS.update(paths)
    return found


def _from_psutil() -> list[dict[str, Any]]:
    try:
        sensors = psutil.sensors_fans() or {}
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for chip, entries in sensors.items():
        for index, entry in enumerate(entries or [], start=1):
            current = getattr(entry, "current", None)
            if current is None:
                continue
            label = getattr(entry, "label", "") or ""
            rows.append({
                "id": f"psutil:{chip}:{index}",
                "chip": str(chip),
                "label": _display_label(str(label), index),
                "rpm": int(current),
                "pwm": None,
                "pwm_percent": None,
                "mode": "unknown",
                "controllable": False,
            })
    return rows


def _mock_state() -> dict[str, Any]:
    return {
        "fans": [
            {
                "id": "mock:cpu",
                "chip": "mock",
                "label": "CPU",
                "rpm": 1956,
                "pwm": 176,
                "pwm_percent": 69,
                "mode": "auto",
                "controllable": False,
            },
            {
                "id": "mock:chassis",
                "chip": "mock",
                "label": "机箱",
                "rpm": 1106,
                "pwm": 140,
                "pwm_percent": 55,
                "mode": "auto",
                "controllable": False,
            },
        ],
        "control": "readonly",
        "reason": "mock",
    }


def _floor() -> int:
    cfg = get_config().fans
    floor = int(cfg.min_pwm_percent)
    return max(1, min(100, floor))


def _decorate(fans: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = get_config().fans
    with _LOCK:
        forced = dict(_FORCED_READONLY)
    for fan in fans:
        if fan["id"] in forced:
            fan["controllable"] = False
        elif not cfg.control_enabled:
            fan["controllable"] = False
    if not fans:
        return {"fans": [], "control": "off", "reason": ""}
    if not cfg.control_enabled:
        return {"fans": fans, "control": "readonly", "reason": "control_disabled"}
    writable = [fan for fan in fans if fan["controllable"]]
    if writable:
        return {"fans": fans, "control": "ready", "reason": ""}
    reason = "readback_mismatch" if forced else "not_writable"
    return {"fans": fans, "control": "readonly", "reason": reason}


def collect_fans(mock_on_failure: bool = True, force_mock: bool = False) -> dict[str, Any]:
    if force_mock:
        return _mock_state()
    try:
        fans = _scan()
    except Exception as exc:
        log.warning("fan collect failed: %s", exc)
        if mock_on_failure:
            return _mock_state()
        raise
    return _decorate(fans)


def public_state() -> dict[str, Any]:
    return collect_fans(mock_on_failure=False, force_mock=False)


def _require_known(fan_id: str) -> dict[str, Path | None]:
    if not _ID_RE.match(fan_id):
        raise FanRejected("not_found", "没有这路风扇")
    with _LOCK:
        paths = _PATHS.get(fan_id)
    if not paths:
        # 目录可能刚变化，重扫一次
        _scan()
        with _LOCK:
            paths = _PATHS.get(fan_id)
    if not paths:
        raise FanRejected("not_found", "没有这路风扇")
    return paths


def _ensure_can_write(fan_id: str) -> dict[str, Path | None]:
    cfg = get_config().fans
    if not cfg.control_enabled:
        raise FanRejected("control_disabled", "调速未开启")
    with _LOCK:
        if fan_id in _FORCED_READONLY:
            raise FanRejected("readback_mismatch", "写入后被系统改回，已停用调速")
    paths = _require_known(fan_id)
    if not _writable(paths.get("pwm")) or not _writable(paths.get("enable")):
        raise FanRejected("not_writable", "系统未提供可写转速")
    return paths


def _check_floor(percent: int) -> int:
    if percent < _floor():
        raise FanRejected("below_floor", f"低于最低转速 {_floor()}%")
    if percent > 100:
        raise FanRejected("below_floor", "转速百分比需在 0–100")
    return percent


def _write_text(path: Path, value: str) -> None:
    try:
        path.write_text(value, encoding="utf-8")
    except OSError as exc:
        raise FanRejected("not_writable", "系统未提供可写转速") from exc


def _force_readonly(fan_id: str) -> None:
    with _LOCK:
        _FORCED_READONLY[fan_id] = "readback_mismatch"


def _apply_many(specs: list[tuple[str, str, int | None]]) -> None:
    """先写完全部目标，再统一等待约 2 秒读回。任一不一致则撤销并标只读。"""
    prepared: list[dict[str, Any]] = []
    for fan_id, mode, percent in specs:
        paths = _ensure_can_write(fan_id)
        enable_path = paths["enable"]
        pwm_path = paths["pwm"]
        assert enable_path is not None and pwm_path is not None
        target_enable = 2 if mode == "auto" and percent is None else 1
        target_pwm = _pwm_from_percent(percent) if percent is not None else None
        prepared.append({
            "id": fan_id,
            "enable_path": enable_path,
            "pwm_path": pwm_path,
            "old_enable": _read_int(enable_path),
            "old_pwm": _read_int(pwm_path),
            "target_enable": target_enable,
            "target_pwm": target_pwm,
        })
    for item in prepared:
        _write_text(item["enable_path"], str(item["target_enable"]))
        if item["target_pwm"] is not None:
            _write_text(item["pwm_path"], str(item["target_pwm"]))
    time.sleep(READBACK_SEC)
    failed = False
    for item in prepared:
        now_enable = _read_int(item["enable_path"])
        now_pwm = _read_int(item["pwm_path"])
        enable_ok = now_enable == item["target_enable"]
        target_pwm = item["target_pwm"]
        pwm_ok = True if target_pwm is None else (
            now_pwm is not None and abs(now_pwm - target_pwm) <= PWM_TOLERANCE
        )
        if enable_ok and pwm_ok:
            continue
        failed = True
        if item["old_enable"] is not None:
            try:
                item["enable_path"].write_text(str(item["old_enable"]), encoding="utf-8")
            except OSError:
                log.warning("fan revert enable failed: %s", item["id"])
        if item["old_pwm"] is not None:
            try:
                item["pwm_path"].write_text(str(item["old_pwm"]), encoding="utf-8")
            except OSError:
                log.warning("fan revert pwm failed: %s", item["id"])
        _force_readonly(item["id"])
    if failed:
        raise FanRejected("readback_mismatch", "写入后被系统改回，已停用调速")


def set_mode(fan_id: str, mode: str) -> dict[str, Any]:
    if mode not in ("auto", "manual"):
        raise FanRejected("not_writable", "模式只能是自动或手动")
    _apply_many([(fan_id, mode, None)])
    return collect_fans(mock_on_failure=False)


def set_pwm(fan_id: str, percent: int) -> dict[str, Any]:
    _check_floor(int(percent))
    _apply_many([(fan_id, "manual", int(percent))])
    return collect_fans(mock_on_failure=False)


def set_preset(preset: str) -> dict[str, Any]:
    cfg = get_config().fans
    table = {
        "silent": cfg.presets.silent,
        "normal": cfg.presets.normal,
        "performance": cfg.presets.performance,
    }
    if preset not in table:
        raise FanRejected("not_writable", "没有这个预设")
    percent = _check_floor(int(table[preset]))
    state = collect_fans(mock_on_failure=False)
    targets = [fan["id"] for fan in state["fans"] if fan.get("controllable")]
    if not targets:
        raise FanRejected("not_writable", "系统未提供可写转速")
    _apply_many([(fan_id, "manual", percent) for fan_id in targets])
    return collect_fans(mock_on_failure=False)
