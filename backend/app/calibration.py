"""展示校准：磁盘身份、风扇通道映射、容量单位。

磁盘和风扇的网页修改写在 SQLite。容量策略的默认值在 config.yaml
的 display.capacity；网页保存后写入 app_kv，优先于配置文件。
config.yaml 在 Compose 里是只读挂载，所以不能靠改文件让界面立刻生效。
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any

_TOKEN_PREFIXES = ("0x", "naa.", "eui.", "wwn-")
_ROLE_NONE = "none"
_FAN_ROLES = {"", "cpu", "chassis", "other"}
_BUS = {"NVME": "NVMe", "SATA": "SATA", "SAS": "SAS", "USB": "USB", "SCSI": "SCSI"}
_KIND = {"HDD", "SSD"}
_ADVERTISED = re.compile(r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)\s*(TB|GB|T|G)\b", re.I)


def normalize_identity_token(value: Any) -> str:
    """序列号 / WWN 比较用。去掉 0x、naa. 和分隔符，再转成大写。"""
    if value is None:
        return ""
    text = str(value).strip().replace(" ", "")
    if not text:
        return ""
    low = text.lower()
    for prefix in _TOKEN_PREFIXES:
        if low.startswith(prefix):
            text = text[len(prefix) :]
            low = text.lower()
    return re.sub(r"[^A-Za-z0-9]", "", text).upper()


def disk_identity(*, serial: Any = None, wwn: Any = None, device: Any = None) -> dict[str, Any]:
    """稳定身份优先用序列号和 WWN。两者都没有时才退回当前盘符，并标成不稳定。

    盘符会随拔插变化，不能把 dev:sda 当成同一块盘的永久身份。
    """
    sn = normalize_identity_token(serial)
    ww = normalize_identity_token(wwn)
    dev = str(device or "").strip().replace("\\", "/")
    if dev.startswith("/dev/"):
        dev = dev[5:]
    dev = Path(dev).name or "unknown"
    if sn and ww:
        key = f"sn:{sn}|wwn:{ww}"
        stable = True
    elif sn:
        key = f"sn:{sn}"
        stable = True
    elif ww:
        key = f"wwn:{ww}"
        stable = True
    else:
        key = f"dev:{dev}"
        stable = False
    return {
        "identity_key": key,
        "serial": sn,
        "wwn": ww,
        "identity_stable": stable,
    }


def _read_small(path: Path) -> str:
    try:
        if not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if not text or len(text) > 128 or "\x00" in text:
        return ""
    return text.splitlines()[0].strip()


def read_block_identity(
    disk_id: str,
    sys_root: Path | None = None,
    by_id_root: Path | None = None,
) -> tuple[str, str]:
    """从 sysfs / by-id 读序列号和 WWN。只读元数据，不碰盘片，休眠盘也不会被叫醒。"""
    if not disk_id:
        return "", ""
    root = sys_root or Path("/sys")
    device = root / "block" / disk_id / "device"
    serial = _read_small(device / "serial")
    wwn = ""
    wwid = _read_small(device / "wwid")
    if wwid:
        low = wwid.lower()
        if low.startswith("naa.") or low.startswith("eui."):
            wwn = wwid
    nguid = _read_small(device / "nguid")
    if not wwn and nguid:
        wwn = nguid
    links = by_id_root if by_id_root is not None else Path("/dev/disk/by-id")
    if not wwn and links.is_dir():
        try:
            entries = list(links.iterdir())
        except OSError:
            entries = []
        for entry in entries:
            name = entry.name
            if not (name.startswith("wwn-") or name.startswith("nvme-eui.")):
                continue
            try:
                target = Path(os.path.realpath(entry)).name
            except OSError:
                continue
            if target != disk_id:
                continue
            wwn = name[4:] if name.startswith("wwn-") else name.split(".", 1)[-1]
            break
    return serial, wwn


def wwn_from_smart(data: dict[str, Any] | None) -> str:
    if not data:
        return ""
    raw = data.get("wwn")
    if isinstance(raw, dict):
        try:
            naa = int(raw.get("naa"))
            oui = int(raw.get("oui"))
            ident = int(raw.get("id"))
        except (TypeError, ValueError):
            return ""
        value = (naa << 60) | (oui << 36) | ident
        return f"{value:016X}"
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    for key in ("logical_unit_id",):
        text = data.get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def advertised_bytes_from_model(model: str | None) -> int | None:
    """从型号里的 4TB / 500GB 取出厂商标称字节（十进制）。识别不到就返回 None。"""
    if not model:
        return None
    found = list(_ADVERTISED.finditer(str(model)))
    if not found:
        return None
    match = found[-1]
    num = float(match.group(1))
    unit = match.group(2).upper()
    if unit in ("TB", "T"):
        return int(round(num * 1000**4))
    if unit in ("GB", "G"):
        return int(round(num * 1000**3))
    return None


def attach_disk_identity(
    disk: dict[str, Any],
    *,
    sys_root: Path | None = None,
    by_id_root: Path | None = None,
    read_sysfs: bool = True,
) -> None:
    disk_id = str(disk.get("id") or Path(str(disk.get("device") or "")).name)
    serial = disk.get("serial") or ""
    wwn = disk.get("wwn") or ""
    if read_sysfs and not disk.get("mock") and disk_id:
        sys_serial, sys_wwn = read_block_identity(disk_id, sys_root, by_id_root)
        serial = serial or sys_serial
        wwn = wwn or sys_wwn
    if disk.get("label_bytes") in (None, "") and disk.get("model"):
        disk["label_bytes"] = advertised_bytes_from_model(str(disk.get("model") or ""))
    disk.update(disk_identity(serial=serial, wwn=wwn, device=disk_id))


def match_disk_calibration(disk: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """先比完整身份键。键不一致时，只要序列号或 WWN 对得上仍视为同一块盘。

    多行同时命中则放弃，避免把设置套到另一块盘上。
    """
    key = str(disk.get("identity_key") or "")
    serial = str(disk.get("serial") or "")
    wwn = str(disk.get("wwn") or "")
    by_key = {str(row.get("identity_key") or ""): row for row in rows}
    if key and key in by_key:
        return by_key[key]
    if serial:
        hits = [row for row in rows if str(row.get("serial") or "") == serial]
        if wwn:
            both = [row for row in hits if str(row.get("wwn") or "") == wwn]
            if len(both) == 1:
                return both[0]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return None
    if wwn:
        hits = [row for row in rows if str(row.get("wwn") or "") == wwn]
        if len(hits) == 1:
            return hits[0]
    return None


def split_detected_media(media: str | None) -> tuple[str, str]:
    text = (media or "").strip()
    if not text:
        return "", ""
    iface = ""
    kind = ""
    for part in text.split():
        token = part.upper()
        if token in _BUS:
            iface = _BUS[token]
        elif token in _KIND:
            kind = token
    if not iface and not kind:
        return "", text
    return iface, kind


def compose_media(detected: str | None, interface_override: str, media_override: str) -> str:
    iface, kind = split_detected_media(detected)
    if not interface_override and not media_override:
        return (detected or "").strip()
    iface = interface_override or iface
    kind = media_override or kind
    if iface and kind:
        if kind.upper().startswith(iface.upper()):
            return kind
        return f"{iface} {kind}".strip()
    return (iface or kind or (detected or "")).strip()


def apply_disk_calibration(
    disks: list[dict[str, Any]] | None,
    rows: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """套用每块盘的显示名、角色、介质、接口、排序和显隐。隐藏盘仍留在结果里，visible 为假。

    调用方把 visible 为假的盘从总览和磁盘详情里拿掉。排序相同则保持采集顺序。
    """
    indexed: list[tuple[int, dict[str, Any]]] = []
    for index, src in enumerate(disks or []):
        disk = dict(src)
        if not disk.get("identity_key"):
            disk.update(
                disk_identity(
                    serial=disk.get("serial"),
                    wwn=disk.get("wwn"),
                    device=disk.get("id") or disk.get("device"),
                )
            )
        else:
            disk["serial"] = normalize_identity_token(disk.get("serial"))
            disk["wwn"] = normalize_identity_token(disk.get("wwn"))
            disk["identity_stable"] = not str(disk.get("identity_key") or "").startswith("dev:")
        row = match_disk_calibration(disk, list(rows or []))
        detected_role = disk.get("role")
        detected_media = disk.get("media") or ""
        detected_iface, detected_kind = split_detected_media(str(detected_media or ""))
        disk["detected_role"] = detected_role
        disk["detected_media"] = detected_media
        disk["detected_interface"] = detected_iface
        disk["detected_media_kind"] = detected_kind
        visible = True
        label = ""
        role_over = ""
        media_over = ""
        iface_over = ""
        sort_order = 0
        if row:
            visible = bool(row.get("visible", 1))
            label = str(row.get("label") or "").strip()
            role_over = str(row.get("role") or "").strip()
            media_over = str(row.get("media") or "").strip()
            iface_over = str(row.get("interface") or "").strip()
            try:
                sort_order = int(row.get("sort_order") or 0)
            except (TypeError, ValueError):
                sort_order = 0
        disk["visible"] = visible
        disk["label"] = label
        disk["display_name"] = label or str(disk.get("id") or "")
        disk["role_override"] = role_over or None
        disk["media_override"] = media_over
        disk["interface_override"] = iface_over
        if not role_over:
            disk["role"] = detected_role
        elif role_over == _ROLE_NONE:
            disk["role"] = None
        else:
            disk["role"] = role_over
        disk["interface"] = iface_over or detected_iface
        disk["media"] = compose_media(str(detected_media or ""), iface_over, media_over) or None
        disk["sort_order"] = sort_order
        indexed.append((index, disk))
    indexed.sort(key=lambda item: (item[1]["sort_order"], item[0]))
    return [disk for _, disk in indexed]


def visible_disks(disks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [disk for disk in disks or [] if disk.get("visible", True)]


def _norm_key_part(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def fan_channel_key(fan: dict[str, Any]) -> str:
    """芯片名 + 通道号 + 原始标签。hwmon 编号变化时仍能对上同一路。"""
    chip = _norm_key_part(fan.get("chip"))
    raw = _norm_key_part(fan.get("raw_label"))
    fan_id = str(fan.get("id") or "")
    match = re.search(r"fan(\d+)$", fan_id)
    if chip and match:
        return f"{chip}:{match.group(1)}:{raw}"
    return fan_id or "unknown"


def apply_fan_mapping(
    fans: list[dict[str, Any]] | None,
    mappings: list[dict[str, Any]] | None,
    *,
    drop_excluded: bool = True,
) -> list[dict[str, Any]]:
    """按通道映射改角色和首页主显示。排除的通道默认不进入仪表盘。

    不改 controllable / mode_controllable：PWM 不可写时仍是不可调。
    """
    by_key: dict[str, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for row in mappings or []:
        key = str(row.get("channel_key") or "")
        if key:
            by_key[key] = row
        fan_id = str(row.get("fan_id") or "")
        if fan_id and fan_id not in by_id:
            by_id[fan_id] = row
    out: list[dict[str, Any]] = []
    for src in fans or []:
        fan = dict(src)
        fan.setdefault("raw_label", "")
        key = fan_channel_key(fan)
        fan["channel_key"] = key
        row = by_key.get(key) or by_id.get(str(fan.get("id") or ""))
        fan["role_override"] = ""
        fan["primary"] = False
        fan["excluded"] = False
        if row:
            excluded = bool(row.get("excluded"))
            role = str(row.get("role") or "")
            if role not in _FAN_ROLES:
                role = ""
            fan["excluded"] = excluded
            fan["role_override"] = role
            if role == "cpu":
                fan["role"] = "cpu"
                fan["label"] = "CPU"
            elif role == "chassis":
                fan["role"] = "chassis"
                fan["label"] = "机箱"
            elif role == "other":
                fan["role"] = "other"
                raw = str(fan.get("raw_label") or "").strip()
                if fan.get("label") in ("CPU", "机箱"):
                    fan["label"] = raw or "风扇"
            if excluded and drop_excluded:
                continue
            fan["primary"] = bool(row.get("primary")) and not excluded
        out.append(fan)
    seen_primary = False
    for fan in out:
        if fan.get("primary") and not seen_primary:
            seen_primary = True
        else:
            fan["primary"] = False
    return out


def format_capacity(
    nbytes: Any,
    unit: str = "gib",
    decimals: int = 1,
    label_bytes: Any = None,
) -> str:
    """与 web/src/utils/capacity.js 同一口径，供测试锁定。界面只走前端那一个函数。"""
    from app.config import CapacityCfg

    if nbytes is None or nbytes == "":
        return "—"
    try:
        size = float(nbytes)
    except (TypeError, ValueError):
        return "—"
    if math.isnan(size) or size < 0:
        return "—"
    policy = CapacityCfg(unit=unit, decimals=decimals)
    if policy.unit == "label":
        advertised = _positive(label_bytes)
        if advertised is not None:
            return _format_base(advertised, 1000, policy.decimals, ["B", "KB", "MB", "GB", "TB", "PB"])
        return _format_base(size, 1024, policy.decimals, ["B", "KiB", "MiB", "GiB", "TiB", "PiB"])
    if policy.unit == "gb":
        return _format_base(size, 1000, policy.decimals, ["B", "KB", "MB", "GB", "TB", "PB"])
    return _format_base(size, 1024, policy.decimals, ["B", "KiB", "MiB", "GiB", "TiB", "PiB"])


def _positive(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or number <= 0:
        return None
    return number


def _format_base(size: float, base: int, decimals: int, units: list[str]) -> str:
    index = 0
    while size >= base and index < len(units) - 1:
        size /= base
        index += 1
    if index == 0:
        return f"{int(round(size))} {units[0]}"
    return f"{size:.{decimals}f} {units[index]}"


def effective_capacity(cfg: Any, store: Any) -> dict[str, Any]:
    from app.config import CapacityCfg

    unit = cfg.display.capacity.unit
    decimals = cfg.display.capacity.decimals
    source = "config"
    if store is not None:
        saved_unit = store.get_kv("display.capacity_unit")
        saved_decimals = store.get_kv("display.capacity_decimals")
        if saved_unit:
            unit = saved_unit
            source = "db"
        if saved_decimals not in (None, ""):
            decimals = saved_decimals
            source = "db"
    policy = CapacityCfg(unit=unit, decimals=decimals)
    return {
        "unit": policy.unit,
        "decimals": policy.decimals,
        "source": source,
        "config_unit": cfg.display.capacity.unit,
        "config_decimals": cfg.display.capacity.decimals,
    }


def save_capacity(store: Any, unit: str, decimals: int) -> dict[str, Any]:
    from app.config import CapacityCfg, get_config

    policy = CapacityCfg(unit=unit, decimals=decimals)
    store.set_kv("display.capacity_unit", policy.unit)
    store.set_kv("display.capacity_decimals", str(policy.decimals))
    return effective_capacity(get_config(), store)


def clear_capacity_override(store: Any) -> dict[str, Any]:
    from app.config import get_config

    store.delete_kv("display.capacity_unit")
    store.delete_kv("display.capacity_decimals")
    return effective_capacity(get_config(), store)


def republish_disk_calibration(store: Any) -> None:
    from app.state import get_latest, set_latest

    latest = get_latest()
    raw = latest.get("_disks_raw")
    if not raw:
        return
    calibrated = apply_disk_calibration([dict(item) for item in raw], store.list_disk_calibrations())
    updated = dict(latest)
    updated["disks_smart_summary"] = visible_disks(calibrated)
    updated["_disks_raw"] = list(raw)
    set_latest(updated)


def republish_fans() -> None:
    from app.collectors import fans as fan_col
    from app.config import get_config
    from app.state import get_latest, set_latest

    latest = get_latest()
    if not latest:
        return
    state = fan_col.collect_fans(
        mock_on_failure=get_config().collect.mock_on_failure,
        force_mock=bool(latest.get("host_mock")),
    )
    updated = dict(latest)
    updated["fans"] = state.get("fans") or []
    updated["control"] = state.get("control") or "off"
    updated["reason"] = state.get("reason") or ""
    set_latest(updated)
