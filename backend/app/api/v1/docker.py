from fastapi import APIRouter, Depends

from app.api.deps import require_user
from app.state import get_latest

router = APIRouter(tags=["docker"])


@router.get("/docker/containers")
def containers(_user: str = Depends(require_user)):
    latest = get_latest()
    items = [
        {k: v for k, v in c.items() if k != "mock"}
        for c in (latest.get("containers") or [])
    ]
    return {"containers": items}
