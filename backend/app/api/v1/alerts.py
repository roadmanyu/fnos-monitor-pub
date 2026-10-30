from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import require_user
from app.config import get_config
from app.storage.sqlite_store import Store

router = APIRouter(tags=["alerts"])


def get_store() -> Store:
    from app.main import store

    return store


@router.get("/alerts")
def list_alerts(
    limit: int = Query(50, ge=1, le=200),
    severity: str | None = None,
    _user: str = Depends(require_user),
    store: Store = Depends(get_store),
):
    return {"items": store.list_alerts(limit=limit, severity=severity)}


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: int, _user: str = Depends(require_user), store: Store = Depends(get_store)):
    if not store.ack_alert(alert_id):
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "alert not found"}
        )
    return {"ok": True}


@router.get("/alerts/rules")
def rules(_user: str = Depends(require_user)):
    cfg = get_config()
    r = cfg.alerts.rules
    return {
        "enabled": cfg.alerts.enabled,
        "cooldown_default_sec": cfg.alerts.cooldown_default_sec,
        "rules": r.model_dump(),
        "descriptions": [
            {"id": "fs_used_warn", "when": f"挂载使用率 ≥ {r.fs_used_warn_pct}%"},
            {"id": "fs_used_crit", "when": f"挂载使用率 ≥ {r.fs_used_crit_pct}%"},
            {
                "id": "cpu_high",
                "when": f"CPU ≥ {r.cpu_high_pct}% 持续 {r.cpu_high_duration_sec}s",
            },
            {"id": "mem_low", "when": f"内存使用率 ≥ {r.mem_used_warn_pct}%"},
            {"id": "temp_cpu_high", "when": f"CPU 温度 ≥ {r.temp_cpu_warn_c}°C"},
            {"id": "smart_unhealthy", "when": "SMART 失败或坏道相关计数 > 0"},
            {"id": "smart_temp_high", "when": f"盘温 ≥ {cfg.smart.temp_warn_c}°C"},
            {"id": "docker_exited", "when": "容器 exited/dead（或监视名单未 running）"},
        ],
    }


@router.get("/alerts/channels")
def channels(_user: str = Depends(require_user)):
    cfg = get_config()
    urls = cfg.alerts.apprise_urls
    types = []
    for u in urls:
        kind = "webhook"
        low = u.lower()
        if low.startswith("tgram://"):
            kind = "telegram"
        elif "wxwork" in low or "wecom" in low:
            kind = "wecom"
        elif "dingtalk" in low:
            kind = "dingtalk"
        elif "lark" in low or "feishu" in low:
            kind = "feishu"
        elif low.startswith("mailto://"):
            kind = "email"
        elif low.startswith("json://") or low.startswith("form://") or "http" in low:
            kind = "webhook"
        types.append({"type": kind, "configured": True})
    return {
        "count": len(urls),
        "channels": types,
        "supported": ["telegram", "wecom", "dingtalk", "feishu", "email", "webhook"],
        "note": "不含 Bark；请在 config.yaml 的 alerts.apprise_urls 配置后重启",
    }
