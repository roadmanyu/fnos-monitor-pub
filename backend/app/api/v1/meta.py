import socket

from fastapi import APIRouter, Depends

from app.api.deps import require_user
from app.calibration import effective_capacity
from app.config import get_config
from app.state import get_latest
from app.version import app_version

router = APIRouter(tags=["meta"])


@router.get("/health")
def health():
    return {"status": "ok", "api_version": "v1"}


@router.get("/meta")
def meta(_user: str = Depends(require_user)):
    from app.main import store

    cfg = get_config()
    latest = get_latest()
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "unknown"
    return {
        "api_version": "v1",
        "app_version": app_version(),
        "hostname": hostname,
        "last_collect_ts": latest.get("ts"),
        "collect_interval_sec": cfg.collect.interval_sec,
        "fan_min_pwm_percent": cfg.fans.min_pwm_percent,
        "power_rated_watts": cfg.power.rated_watts,
        "disk_bps_cap": cfg.collect.disk_bps_cap,
        "timezone_display": cfg.display.timezone,
        "capacity_display": effective_capacity(cfg, store),
        "mock_mode": bool(latest.get("host_mock"))
        or any(f.get("mock") for f in (latest.get("filesystems") or []))
        or any(d.get("mock") for d in (latest.get("disks_smart_summary") or [])),
    }
