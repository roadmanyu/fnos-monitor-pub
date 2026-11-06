"""文件系统容量。"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import psutil

log = logging.getLogger(__name__)


def collect_filesystems(
    mounts: list[str] | None = None,
    exclude_prefixes: list[str] | None = None,
    mock_on_failure: bool = True,
) -> list[dict[str, Any]]:
    exclude_prefixes = exclude_prefixes or []
    try:
        parts = psutil.disk_partitions(all=False)
        result = []
        for p in parts:
            mp = p.mountpoint
            if mounts:
                if mp not in mounts:
                    continue
            else:
                if any(mp == pref or mp.startswith(pref.rstrip("/") + "/") or mp.startswith(pref)
                       for pref in exclude_prefixes):
                    continue
                # 跳过常见虚拟/容器挂载
                if p.fstype in ("tmpfs", "devtmpfs", "overlay", "squashfs", "proc", "sysfs", "cgroup", "cgroup2"):
                    continue
            try:
                u = psutil.disk_usage(mp)
            except PermissionError:
                continue
            fid = _mount_id(mp)
            result.append(
                {
                    "id": fid,
                    "mount": mp,
                    "device": p.device,
                    "fstype": p.fstype or "",
                    "total_bytes": int(u.total),
                    "used_bytes": int(u.used),
                    "used_pct": round(u.percent, 2),
                }
            )
        if not result and mock_on_failure:
            return _mock_filesystems()
        annotate_filesystem_layouts(result)
        return result
    except Exception as e:
        log.warning("fs collect failed: %s", e)
        if mock_on_failure:
            return _mock_filesystems()
        raise


def _mount_id(mp: str) -> str:
    s = mp.strip("/").replace("/", "_") or "root"
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", s)[:64]


def _mock_filesystems() -> list[dict[str, Any]]:
    specs = [
        ("/", "/dev/sda1", "ext4", "Basic", 64 * 1024**3, 0.40),
        ("/vol1", "/dev/md0", "btrfs", "RAID 5", 18 * 1024**4, 0.48),
        ("/vol2", "/dev/nvme0n1p1", "btrfs", "Basic", 48 * 1024**3, 0.13),
        ("/vol3", "/dev/sdb1", "ext4", "Basic", 120 * 1024**3, 0.73),
    ]
    rows = []
    for mount, device, fstype, layout, total, ratio in specs:
        rows.append({
            "id": _mount_id(mount),
            "mount": mount,
            "device": device,
            "fstype": fstype,
            "layout": layout,
            "total_bytes": total,
            "used_bytes": int(total * ratio),
            "used_pct": round(ratio * 100, 2),
            "mock": True,
        })
    return rows


_DISK_NAME = re.compile(
    r"^(?P<disk>nvme\d+n\d+|mmcblk\d+|nvme\d+c\d+n\d+|(?:sd|vd|hd|xvd)[a-z]+)"
)
_MD_LINE = re.compile(r"^(md\w+)\s*:\s*\S+\s+(raid\d+|linear|multipath)", re.I)
_PROFILE_ORDER = ("raid6", "raid5", "raid10", "raid1c4", "raid1c3", "raid1", "raid0", "dup", "single")


def disk_name_from_node(name: str) -> str | None:
    match = _DISK_NAME.match(name or "")
    if not match:
        return None
    return match.group("disk")


def _block_members(devname: str, sys_root: Path, seen: set[str] | None = None) -> set[str]:
    seen = seen if seen is not None else set()
    if not devname or devname in seen:
        return set()
    seen.add(devname)
    found: set[str] = set()
    base = disk_name_from_node(devname)
    if base:
        found.add(base)
    slaves = sys_root / "block" / devname / "slaves"
    if slaves.is_dir():
        try:
            children = list(slaves.iterdir())
        except OSError:
            children = []
        for slave in children:
            found |= _block_members(slave.name, sys_root, seen)
    return found


def _is_external(disk_id: str, sys_root: Path) -> bool:
    removable = sys_root / "block" / disk_id / "removable"
    try:
        if removable.read_text(encoding="utf-8").strip() == "1":
            return True
    except OSError:
        pass
    device = sys_root / "block" / disk_id / "device"
    if not device.exists():
        return False
    try:
        target = os.path.realpath(device)
    except OSError:
        return False
    return "/usb" in target.lower()


def _is_cache(disk_id: str, mounts: list[str], sys_root: Path) -> bool:
    for mount in mounts:
        text = mount or ""
        if "cache" in text.lower() or "缓存" in text:
            return True
    block = sys_root / "block" / disk_id
    if (block / "bcache").exists():
        return True
    holders = block / "holders"
    if holders.is_dir():
        try:
            names = [p.name.lower() for p in holders.iterdir()]
        except OSError:
            names = []
        if any("bcache" in name or "cache" in name for name in names):
            return True
    return False


def _pool_tag(mount: str) -> str:
    if mount == "/":
        return "系统盘"
    name = mount.rstrip("/").split("/")[-1] or mount
    return name[:16]


def infer_disk_role(disk_id: str, mounts: list[str], sys_root: Path) -> str | None:
    norms = [m for m in mounts if m]
    if any(m == "/" or m == "/boot" or m.startswith("/boot/") for m in norms):
        return "系统盘"
    if _is_external(disk_id, sys_root):
        return "外接"
    if _is_cache(disk_id, norms, sys_root):
        return "缓存"
    data = [m for m in norms if m != "/"]
    if not data:
        return None
    data.sort(key=lambda m: (m.count("/"), len(m)))
    return _pool_tag(data[0])


def annotate_disk_roles(
    disks: list[dict[str, Any]],
    filesystems: list[dict[str, Any]] | None,
    sys_root: Path | None = None,
) -> None:
    """从挂载、阵列成员和 sysfs 推断角标。推断不出时 role 为 None，不编造。"""
    root = sys_root or Path("/sys")
    mounts_by_disk: dict[str, list[str]] = {}
    for fs in filesystems or []:
        device = str(fs.get("device") or "")
        mount = str(fs.get("mount") or "")
        if not device or not mount:
            continue
        for disk_id in _block_members(Path(device).name, root):
            bucket = mounts_by_disk.setdefault(disk_id, [])
            if mount not in bucket:
                bucket.append(mount)
    for disk in disks or []:
        disk_id = str(disk.get("id") or "")
        if not disk_id:
            continue
        disk["role"] = infer_disk_role(disk_id, mounts_by_disk.get(disk_id, []), root)


def _md_levels(proc_root: Path) -> dict[str, str]:
    path = proc_root / "mdstat"
    levels: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return levels
    for line in text.splitlines():
        match = _MD_LINE.match(line.strip())
        if not match:
            continue
        name, kind = match.group(1), match.group(2).lower()
        if kind == "linear":
            levels[name] = "Linear"
        elif kind == "raid10":
            levels[name] = "RAID 10"
        elif kind.startswith("raid"):
            levels[name] = f"RAID {kind[4:]}"
        else:
            levels[name] = kind.upper()
    return levels


def _device_aliases(device: str) -> set[str]:
    path = Path(device)
    names = {path.name}
    if path.name.isdigit():
        names.add(f"md{path.name}")
    if path.exists():
        try:
            names.add(path.resolve().name)
        except OSError:
            pass
    return {name for name in names if name}


def _profile_label(names: list[str]) -> str:
    low = {name.lower() for name in names}
    for name in _PROFILE_ORDER:
        if name not in low:
            continue
        if name == "single":
            return "Basic"
        if name == "dup":
            return "DUP"
        if name == "raid10":
            return "RAID 10"
        if name.startswith("raid1c"):
            return "RAID 1"
        if name.startswith("raid"):
            return f"RAID {name[4:]}"
    return "Basic"


def _btrfs_layout(device: str, sys_root: Path) -> str | None:
    root = sys_root / "fs" / "btrfs"
    if not root.is_dir():
        return None
    aliases = _device_aliases(device)
    try:
        uuid_dirs = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return None
    for uuid_dir in uuid_dirs:
        devices = uuid_dir / "devices"
        if not devices.is_dir():
            continue
        try:
            present = {p.name for p in devices.iterdir()}
        except OSError:
            continue
        if not (aliases & present):
            continue
        data = uuid_dir / "allocation" / "data"
        if not data.is_dir():
            return "Basic"
        try:
            profiles = [p.name for p in data.iterdir() if p.is_dir()]
        except OSError:
            return "Basic"
        return _profile_label(profiles)
    return None


def _layout_label(device: str, fstype: str, sys_root: Path, proc_root: Path) -> str:
    levels = _md_levels(proc_root)
    for name in _device_aliases(device):
        if name in levels:
            return levels[name]
    btrfs = _btrfs_layout(device, sys_root)
    if btrfs:
        return btrfs
    if fstype:
        return "Basic"
    return ""


def annotate_filesystem_layouts(
    rows: list[dict[str, Any]],
    sys_root: Path | None = None,
    proc_root: Path | None = None,
) -> None:
    """补上 [level/type]：mdstat 的 RAID、btrfs profile，否则单盘为 Basic。"""
    sys_root = sys_root or Path("/sys")
    proc_root = proc_root or Path("/proc")
    for row in rows or []:
        if row.get("layout"):
            continue
        row["layout"] = _layout_label(
            str(row.get("device") or ""),
            str(row.get("fstype") or ""),
            sys_root,
            proc_root,
        )
