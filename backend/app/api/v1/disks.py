from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_user
from app.state import get_latest

router = APIRouter(tags=["disks"])


@router.get("/disks")
def list_disks(_user: str = Depends(require_user)):
    latest = get_latest()
    filesystems = latest.get("filesystems") or []
    smart = {d["id"]: d for d in (latest.get("disks_smart_summary") or []) if d.get("id")}
    return {
        "filesystems": filesystems,
        "smart": list(smart.values()),
    }


@router.get("/disks/{disk_id}/smart")
def disk_smart(disk_id: str, _user: str = Depends(require_user)):
    from app.main import collector

    detail = None
    if collector:
        detail = collector.get_smart_detail(disk_id)
    if not detail:
        # 回退摘要
        latest = get_latest()
        for d in latest.get("disks_smart_summary") or []:
            if d.get("id") == disk_id:
                detail = {**d, "attrs": []}
                break
    if not detail:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "disk not found"}
        )
    return {
        "id": detail.get("id"),
        "healthy": detail.get("healthy"),
        "temp_c": detail.get("temp_c"),
        "attrs": detail.get("attrs") or [],
        "raw_updated_ts": get_latest().get("ts"),
        "standby_skipped": bool(detail.get("skipped_standby")),
        "model": detail.get("model"),
        "power_on_hours": detail.get("power_on_hours"),
    }
