"""高级设置：采集周期、SMART、插拔去抖、界面分级刷新。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import require_user
from app.config import get_config
from app.tuning import clear_tuning, save_tuning, tuning_snapshot

router = APIRouter(tags=["tuning"])


def _store():
    from app.main import store

    if store is None:
        raise HTTPException(status_code=503, detail={"code": "starting", "message": "服务还在启动"})
    return store


class TuningBody(BaseModel):
    values: dict[str, object]


@router.get("/tuning")
def get_tuning(_user: str = Depends(require_user)):
    return tuning_snapshot(get_config())


@router.put("/tuning")
def put_tuning(body: TuningBody, _user: str = Depends(require_user)):
    try:
        return save_tuning(get_config(), _store(), dict(body.values))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid", "message": str(exc)}) from exc


@router.delete("/tuning")
def delete_tuning(_user: str = Depends(require_user)):
    return clear_tuning(get_config(), _store())
