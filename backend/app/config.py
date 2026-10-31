"""配置加载。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ServerCfg(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8787


class AuthCfg(BaseModel):
    username: str = "admin"
    password_hash: str = ""
    jwt_secret: str = "change-me"
    jwt_expire_sec: int = 86400


class CollectCfg(BaseModel):
    interval_sec: int = 2
    fs_interval_sec: int = 60
    retention_days: int = 7
    mock_on_failure: bool = True
    filesystem_mounts: list[str] = Field(default_factory=list)
    filesystem_exclude_prefixes: list[str] = Field(default_factory=list)
    # 0 = 磁盘吞吐条按近期峰值归一；大于 0 时用该字节/秒作为满格
    disk_bps_cap: float = 0


class PowerCfg(BaseModel):
    # 电源额定功率（瓦）。进度条 = 当前功耗 / 该值。0 表示只显示瓦数、不画百分比。
    rated_watts: float = 200


class FanPresetsCfg(BaseModel):
    silent: int = 30
    normal: int = 55
    performance: int = 85


class FansCfg(BaseModel):
    # 默认允许写 hwmon PWM。没有可写节点时接口仍拒绝，界面保持只读。
    control_enabled: bool = True
    # 手动转速下限（百分比）。低于该值的请求直接 409，避免把风扇停转。
    min_pwm_percent: int = 25
    presets: FanPresetsCfg = Field(default_factory=FanPresetsCfg)


class SmartCfg(BaseModel):
    enabled: bool = True
    interval_sec: int = 900
    devices: list[str] = Field(default_factory=list)
    skip_standby: bool = True
    temp_warn_c: float = 55


class DockerCfg(BaseModel):
    enabled: bool = True
    watch_containers: list[str] = Field(default_factory=list)


class AlertRulesCfg(BaseModel):
    fs_used_warn_pct: float = 85
    fs_used_crit_pct: float = 95
    cpu_high_pct: float = 90
    cpu_high_duration_sec: int = 600
    mem_used_warn_pct: float = 90
    temp_cpu_warn_c: float = 85


class AlertsCfg(BaseModel):
    enabled: bool = True
    cooldown_default_sec: int = 3600
    apprise_urls: list[str] = Field(default_factory=list)
    rules: AlertRulesCfg = Field(default_factory=AlertRulesCfg)


class DisplayCfg(BaseModel):
    timezone: str = "Asia/Shanghai"


class AppConfig(BaseModel):
    server: ServerCfg = Field(default_factory=ServerCfg)
    auth: AuthCfg = Field(default_factory=AuthCfg)
    collect: CollectCfg = Field(default_factory=CollectCfg)
    smart: SmartCfg = Field(default_factory=SmartCfg)
    docker: DockerCfg = Field(default_factory=DockerCfg)
    power: PowerCfg = Field(default_factory=PowerCfg)
    fans: FansCfg = Field(default_factory=FansCfg)
    alerts: AlertsCfg = Field(default_factory=AlertsCfg)
    display: DisplayCfg = Field(default_factory=DisplayCfg)


_config: AppConfig | None = None


def _find_config_path() -> Path:
    env = os.environ.get("MONITOR_CONFIG")
    if env:
        return Path(env)
    candidates = [
        Path("/app/config.yaml"),
        Path(__file__).resolve().parents[2] / "config.yaml",
        Path.cwd() / "config.yaml",
    ]
    for p in candidates:
        if p.is_file():
            return p
    example = Path(__file__).resolve().parents[2] / "config.example.yaml"
    return example


def load_config(path: Path | None = None) -> AppConfig:
    global _config
    p = path or _find_config_path()
    data: dict[str, Any] = {}
    if p.is_file():
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    cfg = AppConfig.model_validate(data)
    # 环境变量覆盖
    if os.environ.get("MONITOR_JWT_SECRET"):
        cfg.auth.jwt_secret = os.environ["MONITOR_JWT_SECRET"]
    if os.environ.get("MONITOR_APPRISE_URLS"):
        cfg.alerts.apprise_urls = [
            u.strip() for u in os.environ["MONITOR_APPRISE_URLS"].split(",") if u.strip()
        ]
    _config = cfg
    return cfg


def get_config() -> AppConfig:
    if _config is None:
        return load_config()
    return _config


def data_dir() -> Path:
    d = Path(os.environ.get("MONITOR_DATA_DIR", "/data"))
    if not d.exists():
        # 开发机回退
        d = Path(__file__).resolve().parents[2] / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d
