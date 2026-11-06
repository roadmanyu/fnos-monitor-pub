"""采集与界面刷新的可调项。

config.yaml 在 Compose 里只读挂载。网页保存写到 SQLite app_kv（键前缀 tune.），
并改内存里的配置，下一轮采集就用新值。和容量校准同一套「库优先于文件」的做法。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.config import AppConfig
from app.storage.sqlite_store import Store

KV_PREFIX = "tune."


@dataclass(frozen=True)
class TuneField:
    key: str
    label: str
    unit: str
    kind: str
    min: float | None
    max: float | None
    hint: str
    group: str
    read: Callable[[AppConfig], Any]
    write: Callable[[AppConfig, Any], None]


def _fields() -> list[TuneField]:
    return [
        TuneField(
            "collect.interval_sec",
            "主机采集周期",
            "秒",
            "int",
            1,
            60,
            "主机、Docker、风扇的采样周期。总览上的快刷新另外看「总览刷新」。",
            "采集",
            lambda cfg: cfg.collect.interval_sec,
            lambda cfg, value: setattr(cfg.collect, "interval_sec", value),
        ),
        TuneField(
            "collect.fs_interval_sec",
            "文件系统采集周期",
            "秒",
            "int",
            5,
            86400,
            "存储池容量的实际读盘周期。界面上可以更慢地换上这份缓存。",
            "采集",
            lambda cfg: cfg.collect.fs_interval_sec,
            lambda cfg, value: setattr(cfg.collect, "fs_interval_sec", value),
        ),
        TuneField(
            "collect.disk_plug_debounce_sec",
            "硬盘插拔去抖",
            "秒",
            "int",
            0,
            300,
            "盘符集合变化后，连续稳定这么多秒才重新读取 SMART。0 表示立刻接受。去抖期间不跑 smartctl。",
            "采集",
            lambda cfg: cfg.collect.disk_plug_debounce_sec,
            lambda cfg, value: setattr(cfg.collect, "disk_plug_debounce_sec", value),
        ),
        TuneField(
            "collect.disk_bps_cap",
            "磁盘吞吐满格",
            "字节/秒",
            "float",
            0,
            10**15,
            "资源卡磁盘条的满格。0 表示按近期采样峰值归一。",
            "采集",
            lambda cfg: cfg.collect.disk_bps_cap,
            lambda cfg, value: setattr(cfg.collect, "disk_bps_cap", value),
        ),
        TuneField(
            "collect.retention_days",
            "时序保留",
            "天",
            "int",
            1,
            90,
            "metric_points 保留天数。告警历史仍固定 30 天。",
            "采集",
            lambda cfg: cfg.collect.retention_days,
            lambda cfg, value: setattr(cfg.collect, "retention_days", value),
        ),
        TuneField(
            "collect.mock_on_failure",
            "失败时模拟",
            "",
            "bool",
            None,
            None,
            "磁盘、SMART、Docker 或主机采集失败时填入模拟数据。",
            "采集",
            lambda cfg: cfg.collect.mock_on_failure,
            lambda cfg, value: setattr(cfg.collect, "mock_on_failure", value),
        ),
        TuneField(
            "docker.enabled",
            "Docker 采集",
            "",
            "bool",
            None,
            None,
            "关闭后不再列出容器。",
            "采集",
            lambda cfg: cfg.docker.enabled,
            lambda cfg, value: setattr(cfg.docker, "enabled", value),
        ),
        TuneField(
            "smart.enabled",
            "SMART 采集",
            "",
            "bool",
            None,
            None,
            "关闭后不再刷新磁盘健康。",
            "SMART",
            lambda cfg: cfg.smart.enabled,
            lambda cfg, value: setattr(cfg.smart, "enabled", value),
        ),
        TuneField(
            "smart.interval_sec",
            "SMART 采集周期",
            "秒",
            "int",
            30,
            86400,
            "smartctl 的间隔。界面上的 SMART 卡片可以更慢地换上这份缓存。",
            "SMART",
            lambda cfg: cfg.smart.interval_sec,
            lambda cfg, value: setattr(cfg.smart, "interval_sec", value),
        ),
        TuneField(
            "smart.skip_standby",
            "跳过休眠盘",
            "",
            "bool",
            None,
            None,
            "已休眠的盘不唤醒。",
            "SMART",
            lambda cfg: cfg.smart.skip_standby,
            lambda cfg, value: setattr(cfg.smart, "skip_standby", value),
        ),
        TuneField(
            "smart.temp_warn_c",
            "盘温告警",
            "°C",
            "float",
            20,
            90,
            "达到该温度记一条警告。",
            "SMART",
            lambda cfg: cfg.smart.temp_warn_c,
            lambda cfg, value: setattr(cfg.smart, "temp_warn_c", value),
        ),
        TuneField(
            "display.refresh.overview_sec",
            "总览刷新",
            "秒",
            "int",
            1,
            60,
            "主机、网络、趋势、Docker 的界面轮询。默认 1 秒，不额外读盘。",
            "界面",
            lambda cfg: cfg.display.refresh.overview_sec,
            lambda cfg, value: setattr(cfg.display.refresh, "overview_sec", value),
        ),
        TuneField(
            "display.refresh.disk_sec",
            "磁盘界面刷新",
            "秒",
            "int",
            5,
            3600,
            "存储池容量在界面上更换的周期。真正读盘仍按文件系统采集周期。",
            "界面",
            lambda cfg: cfg.display.refresh.disk_sec,
            lambda cfg, value: setattr(cfg.display.refresh, "disk_sec", value),
        ),
        TuneField(
            "display.refresh.smart_sec",
            "SMART 界面刷新",
            "秒",
            "int",
            5,
            3600,
            "硬盘健康摘要在界面上更换的周期。真正的 smartctl 仍按 SMART 采集周期。",
            "界面",
            lambda cfg: cfg.display.refresh.smart_sec,
            lambda cfg, value: setattr(cfg.display.refresh, "smart_sec", value),
        ),
    ]


FIELDS: list[TuneField] = _fields()
_BY_KEY = {field.key: field for field in FIELDS}
_baseline: dict[str, Any] = {}


def capture_baseline(cfg: AppConfig, force: bool = False) -> None:
    """记下 YAML / 默认值。重置时回到这里，而不是回到已被网页改过的内存值。"""
    if _baseline and not force:
        return
    _baseline.clear()
    for field in FIELDS:
        _baseline[field.key] = field.read(cfg)


def _kv_key(key: str) -> str:
    return KV_PREFIX + key


def _coerce(field: TuneField, value: Any) -> Any:
    if field.kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0", "yes", "no"):
            return value.strip().lower() in ("true", "1", "yes")
        raise ValueError(f"{field.label}需要是开关")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field.label}需要是数字") from exc
    if field.kind == "int":
        if abs(number - round(number)) > 1e-6:
            raise ValueError(f"{field.label}需要是整数")
        number = int(round(number))
    if field.min is not None and number < field.min:
        raise ValueError(f"{field.label}不能小于 {field.min:g}")
    if field.max is not None and number > field.max:
        raise ValueError(f"{field.label}不能大于 {field.max:g}")
    return int(number) if field.kind == "int" else float(number)


def _public(field: TuneField, cfg: AppConfig) -> dict[str, Any]:
    value = field.read(cfg)
    config_value = _baseline.get(field.key, value)
    same = value == config_value
    return {
        "key": field.key,
        "label": field.label,
        "unit": field.unit,
        "kind": field.kind,
        "min": field.min,
        "max": field.max,
        "hint": field.hint,
        "group": field.group,
        "value": value,
        "config": config_value,
        "source": "config" if same else "db",
    }


def tuning_snapshot(cfg: AppConfig) -> dict[str, Any]:
    if not _baseline:
        capture_baseline(cfg)
    return {"items": [_public(field, cfg) for field in FIELDS]}


def apply_stored_tuning(cfg: AppConfig, store: Store) -> None:
    if not _baseline:
        capture_baseline(cfg)
    for field in FIELDS:
        raw = store.get_kv(_kv_key(field.key))
        if raw is None or raw == "":
            continue
        try:
            value = _coerce(field, _parse_stored(raw, field.kind))
        except ValueError:
            continue
        field.write(cfg, value)


def _parse_stored(raw: str, kind: str) -> Any:
    text = raw.strip()
    if kind == "bool":
        return text.lower() in ("1", "true", "yes")
    if kind == "int":
        return int(float(text))
    return float(text)


def save_tuning(cfg: AppConfig, store: Store, values: dict[str, Any]) -> dict[str, Any]:
    if not _baseline:
        capture_baseline(cfg)
    unknown = [key for key in values if key not in _BY_KEY]
    if unknown:
        raise ValueError("有无法识别的配置项")
    coerced: dict[str, Any] = {}
    for key, raw in values.items():
        coerced[key] = _coerce(_BY_KEY[key], raw)
    for key, value in coerced.items():
        field = _BY_KEY[key]
        field.write(cfg, value)
        if value == _baseline.get(key):
            store.delete_kv(_kv_key(key))
        else:
            store.set_kv(_kv_key(key), _dump(value))
    return tuning_snapshot(cfg)


def clear_tuning(cfg: AppConfig, store: Store) -> dict[str, Any]:
    if not _baseline:
        capture_baseline(cfg)
    for field in FIELDS:
        field.write(cfg, _baseline[field.key])
        store.delete_kv(_kv_key(field.key))
    return tuning_snapshot(cfg)


def _dump(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return str(value)
    return str(int(value) if isinstance(value, int) else value)
