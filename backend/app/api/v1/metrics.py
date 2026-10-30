from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_user
from app.collectors.host import current_public_ipv4
from app.state import get_latest
from app.storage.sqlite_store import Store

router = APIRouter(tags=["metrics"])


def get_store() -> Store:
    from app.main import store

    return store


@router.get("/metrics/snapshot")
def snapshot(_user: str = Depends(require_user)):
    latest = get_latest()
    if not latest:
        return {
            "ts": None,
            "host": {},
            "filesystems": [],
            "disks_smart_summary": [],
            "docker": {"running": 0, "stopped": 0, "total": 0},
        }
    host = dict(latest.get("host") or {})
    if host:
        host["public_ipv4"] = current_public_ipv4()
    return {
        "ts": latest.get("ts"),
        "host": host,
        "filesystems": [
            {k: v for k, v in fs.items() if k != "mock"}
            for fs in (latest.get("filesystems") or [])
        ],
        "disks_smart_summary": [
            {k: v for k, v in d.items() if k != "mock"}
            for d in (latest.get("disks_smart_summary") or [])
        ],
        "docker": latest.get("docker")
        or {"running": 0, "stopped": 0, "total": 0},
    }


@router.get("/metrics/history")
def history(
    metric: str = Query(...),
    from_ts: str | None = Query(None, alias="from"),
    to_ts: str | None = Query(None, alias="to"),
    step: int = Query(60),
    _user: str = Depends(require_user),
    store: Store = Depends(get_store),
):
    now = datetime.now(timezone.utc)
    if not to_ts:
        to_ts = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if not from_ts:
        from_ts = (now - timedelta(hours=1)).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
    points = store.history(metric, from_ts, to_ts, step_sec=step)
    return {"metric": metric, "step_sec": step, "points": points}
