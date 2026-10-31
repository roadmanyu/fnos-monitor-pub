"""风扇读数与调速。调速只接受已发现的风扇 id，不接受路径。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import require_user
from app.collectors.fans import FanRejected, public_state, set_mode, set_preset, set_pwm

router = APIRouter(tags=["fans"])


class ModeBody(BaseModel):
    mode: str = Field(pattern="^(auto|manual)$")


class PwmBody(BaseModel):
    percent: int


class PresetBody(BaseModel):
    preset: str = Field(pattern="^(silent|normal|performance)$")


def _reject(exc: FanRejected) -> HTTPException:
    status = 404 if exc.code == "not_found" else 409
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})


@router.get("/fans")
def get_fans(_user: str = Depends(require_user)):
    try:
        return public_state()
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "collect_failed", "message": "读取风扇失败"}) from exc


@router.post("/fans/preset")
def post_preset(body: PresetBody, _user: str = Depends(require_user)):
    try:
        return set_preset(body.preset)
    except FanRejected as exc:
        raise _reject(exc) from exc


@router.post("/fans/{fan_id}/mode")
def post_mode(fan_id: str, body: ModeBody, _user: str = Depends(require_user)):
    try:
        return set_mode(fan_id, body.mode)
    except FanRejected as exc:
        raise _reject(exc) from exc


@router.post("/fans/{fan_id}/pwm")
def post_pwm(fan_id: str, body: PwmBody, _user: str = Depends(require_user)):
    try:
        return set_pwm(fan_id, body.percent)
    except FanRejected as exc:
        raise _reject(exc) from exc
