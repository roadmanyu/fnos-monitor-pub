"""展示校准：容量策略、硬盘身份、风扇通道。"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import require_user
from app.calibration import (
    apply_disk_calibration,
    clear_capacity_override,
    disk_identity,
    effective_capacity,
    republish_disk_calibration,
    republish_fans,
    save_capacity,
)
from app.collectors.fans import fans_for_calibration
from app.config import get_config
from app.state import get_latest

router = APIRouter(tags=["calibration"])

_KEY_RE = re.compile(
    r"^(?:sn:[A-Z0-9]{1,64}(?:\|wwn:[A-Z0-9]{1,64})?|wwn:[A-Z0-9]{1,64}|dev:[A-Za-z0-9._-]{1,64})$"
)
_CHANNEL_RE = re.compile(r"^[A-Za-z0-9_.:|-]{1,160}$")
_PLAIN = re.compile(r"^[^\r\n\t]{0,32}$")
_FAN_ROLES = {"", "cpu", "chassis", "other"}


def _store():
    from app.main import store

    if store is None:
        raise HTTPException(status_code=503, detail={"code": "starting", "message": "服务还在启动"})
    return store


def _bad(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "invalid", "message": message})


class CapacityBody(BaseModel):
    unit: str
    decimals: int = Field(ge=0, le=3)


class DiskItem(BaseModel):
    identity_key: str
    serial: str = ""
    wwn: str = ""
    visible: bool = True
    label: str = ""
    role: str = ""
    media: str = ""
    interface: str = ""
    sort_order: int = 0


class DiskBody(BaseModel):
    items: list[DiskItem]


class FanItem(BaseModel):
    channel_key: str
    fan_id: str = ""
    role: str = ""
    primary: bool = False
    excluded: bool = False


class FanBody(BaseModel):
    items: list[FanItem]


def _detected_disks(store) -> list[dict]:
    latest = get_latest()
    raw = latest.get("_disks_raw")
    if raw:
        return apply_disk_calibration([dict(item) for item in raw], store.list_disk_calibrations())
    summary = latest.get("disks_smart_summary") or []
    return apply_disk_calibration([dict(item) for item in summary], store.list_disk_calibrations())


def _public_disk(disk: dict) -> dict:
    return {
        "id": disk.get("id"),
        "model": disk.get("model") or "",
        "serial": disk.get("serial") or "",
        "wwn": disk.get("wwn") or "",
        "identity_key": disk.get("identity_key"),
        "identity_stable": bool(disk.get("identity_stable")),
        "visible": bool(disk.get("visible", True)),
        "label": disk.get("label") or "",
        "display_name": disk.get("display_name") or disk.get("id"),
        "role": disk.get("role"),
        "role_override": disk.get("role_override"),
        "detected_role": disk.get("detected_role"),
        "media": disk.get("media"),
        "media_override": disk.get("media_override") or "",
        "detected_media": disk.get("detected_media") or "",
        "interface": disk.get("interface") or "",
        "interface_override": disk.get("interface_override") or "",
        "detected_interface": disk.get("detected_interface") or "",
        "sort_order": disk.get("sort_order") or 0,
        "capacity_bytes": disk.get("capacity_bytes"),
        "label_bytes": disk.get("label_bytes"),
        "temp_c": disk.get("temp_c"),
        "healthy": disk.get("healthy"),
        "skipped_standby": bool(disk.get("skipped_standby")),
    }


def _public_fan(fan: dict) -> dict:
    return {
        "id": fan.get("id"),
        "channel_key": fan.get("channel_key"),
        "chip": fan.get("chip") or "",
        "raw_label": fan.get("raw_label") or "",
        "label": fan.get("label") or "",
        "role": fan.get("role") or "other",
        "role_override": fan.get("role_override") or "",
        "primary": bool(fan.get("primary")),
        "excluded": bool(fan.get("excluded")),
        "rpm": fan.get("rpm"),
        "controllable": bool(fan.get("controllable")),
        "mode_controllable": bool(fan.get("mode_controllable")),
    }


@router.get("/calibration")
def get_calibration(_user: str = Depends(require_user)):
    store = _store()
    disks = [_public_disk(disk) for disk in _detected_disks(store)]
    try:
        fans = [_public_fan(fan) for fan in fans_for_calibration()]
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "collect_failed", "message": "读取风扇失败"}) from exc
    return {
        "capacity": effective_capacity(get_config(), store),
        "disks": disks,
        "fans": fans,
    }


@router.put("/calibration/capacity")
def put_capacity(body: CapacityBody, _user: str = Depends(require_user)):
    store = _store()
    saved = save_capacity(store, body.unit, body.decimals)
    return saved


@router.delete("/calibration/capacity")
def delete_capacity(_user: str = Depends(require_user)):
    store = _store()
    return clear_capacity_override(store)


def _check_text(value: str, field: str, limit: int) -> str:
    text = value.strip()
    if len(text) > limit or not _PLAIN.match(text):
        raise _bad(f"{field}不能包含换行，最长 {limit} 个字符")
    return text


@router.put("/calibration/disks")
def put_disks(body: DiskBody, _user: str = Depends(require_user)):
    store = _store()
    items = []
    seen: set[str] = set()
    for item in body.items:
        key = item.identity_key.strip()
        if not _KEY_RE.match(key):
            raise _bad("磁盘身份无效")
        if key in seen:
            raise _bad("磁盘身份重复")
        seen.add(key)
        device = key[4:] if key.startswith("dev:") else "unknown"
        expect = disk_identity(serial=item.serial, wwn=item.wwn, device=device)
        if expect["identity_key"] != key:
            raise _bad("磁盘身份和序列号不一致")
        label = _check_text(item.label, "名称", 32)
        role = _check_text(item.role, "角色", 16)
        media = _check_text(item.media, "介质", 16)
        interface = _check_text(item.interface, "接口", 16)
        if item.sort_order < -999 or item.sort_order > 999:
            raise _bad("排序需要在 -999 到 999 之间")
        items.append(
            {
                "identity_key": key,
                "serial": expect["serial"],
                "wwn": expect["wwn"],
                "visible": item.visible,
                "label": label,
                "role": role,
                "media": media,
                "interface": interface,
                "sort_order": item.sort_order,
            }
        )
    store.upsert_disk_calibrations(items)
    republish_disk_calibration(store)
    return {"disks": [_public_disk(disk) for disk in _detected_disks(store)]}


@router.put("/calibration/fans")
def put_fans(body: FanBody, _user: str = Depends(require_user)):
    store = _store()
    items = []
    seen: set[str] = set()
    primary_at = -1
    for item in body.items:
        key = item.channel_key.strip()
        if not _CHANNEL_RE.match(key):
            raise _bad("风扇通道无效")
        if key in seen:
            raise _bad("风扇通道重复")
        seen.add(key)
        role = item.role.strip()
        if role not in _FAN_ROLES:
            raise _bad("风扇角色只能是自动、CPU、机箱或其它")
        fan_id = item.fan_id.strip()
        if fan_id and not _CHANNEL_RE.match(fan_id):
            raise _bad("风扇编号无效")
        excluded = bool(item.excluded)
        primary = bool(item.primary) and not excluded
        if primary:
            primary_at = len(items)
        items.append(
            {
                "channel_key": key,
                "fan_id": fan_id,
                "role": role,
                "primary": primary,
                "excluded": excluded,
            }
        )
    if primary_at >= 0:
        for index, item in enumerate(items):
            item["primary"] = index == primary_at
    store.upsert_fan_maps(items)
    republish_fans()
    try:
        fans = [_public_fan(fan) for fan in fans_for_calibration()]
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "collect_failed", "message": "读取风扇失败"}) from exc
    return {"fans": fans}
