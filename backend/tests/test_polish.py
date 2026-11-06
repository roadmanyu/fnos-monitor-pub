"""采集周期、3 分钟历史、磁盘角色、阵列徽章、风扇可调性。"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.collectors.disk import annotate_disk_roles, annotate_filesystem_layouts
from app.collectors.fans import _append_channel, _channel_flags, _role
from app.collectors.host import format_link_speed
from app.config import AppConfig
from app.storage.sqlite_store import Store


class DefaultsTest(unittest.TestCase):
    def test_collect_interval_and_fan_switch(self):
        cfg = AppConfig()
        self.assertEqual(cfg.collect.interval_sec, 1)
        self.assertTrue(cfg.fans.control_enabled)


class LinkSpeedTest(unittest.TestCase):
    def test_formats(self):
        self.assertIsNone(format_link_speed(None))
        self.assertIsNone(format_link_speed(0))
        self.assertIsNone(format_link_speed(-1))
        self.assertEqual(format_link_speed(100), "100M")
        self.assertEqual(format_link_speed(1000), "1G")
        self.assertEqual(format_link_speed(2500), "2.5G")
        self.assertEqual(format_link_speed(10000), "10G")


class DiskRoleTest(unittest.TestCase):
    def test_roles_from_mounts_and_sysfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, removable in (("sda", "0"), ("sdb", "0"), ("sdc", "1"), ("nvme0n1", "0")):
                block = root / "block" / name
                block.mkdir(parents=True)
                (block / "removable").write_text(removable, encoding="utf-8")
            cache = root / "block" / "nvme0n1" / "bcache"
            cache.mkdir()
            md = root / "block" / "md0" / "slaves"
            md.mkdir(parents=True)
            (md / "sdb1").mkdir()
            disks = [
                {"id": "sda"},
                {"id": "sdb"},
                {"id": "sdc"},
                {"id": "nvme0n1"},
            ]
            filesystems = [
                {"device": "/dev/sda1", "mount": "/"},
                {"device": "/dev/md0", "mount": "/vol1"},
                {"device": "/dev/sdc1", "mount": "/mnt/usb"},
            ]
            annotate_disk_roles(disks, filesystems, sys_root=root)
            self.assertEqual(disks[0]["role"], "系统盘")
            self.assertEqual(disks[1]["role"], "vol1")
            self.assertEqual(disks[2]["role"], "外接")
            self.assertEqual(disks[3]["role"], "缓存")

    def test_pool_badges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = root / "proc"
            sys_root = root / "sys"
            proc.mkdir()
            (proc / "mdstat").write_text(
                "Personalities : [raid5]\nmd0 : active raid5 sdb1[0] sdc1[1]\n",
                encoding="utf-8",
            )
            uuid = sys_root / "fs" / "btrfs" / "abc"
            (uuid / "devices").mkdir(parents=True)
            (uuid / "devices" / "nvme0n1p1").mkdir()
            (uuid / "allocation" / "data" / "raid1").mkdir(parents=True)
            rows = [
                {"device": "/dev/md0", "fstype": "btrfs"},
                {"device": "/dev/nvme0n1p1", "fstype": "btrfs"},
                {"device": "/dev/sda1", "fstype": "ext4"},
            ]
            annotate_filesystem_layouts(rows, sys_root=sys_root, proc_root=proc)
            self.assertEqual(rows[0]["layout"], "RAID 5")
            self.assertEqual(rows[1]["layout"], "RAID 1")
            self.assertEqual(rows[2]["layout"], "Basic")


class FanDetectTest(unittest.TestCase):
    def test_role_labels(self):
        self.assertEqual(_role("CPU Fan"), "cpu")
        self.assertEqual(_role("System Fan"), "chassis")
        self.assertEqual(_role("风扇2"), "other")

    def test_missing_pwm_is_not_controllable(self):
        controllable, mode_ok = _channel_flags(None, None)
        self.assertFalse(controllable)
        self.assertFalse(mode_ok)

    def test_pwm_without_enable_keeps_slider_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            hw = Path(tmp)
            (hw / "name").write_text("nct6775", encoding="utf-8")
            (hw / "fan1_label").write_text("CPU Fan", encoding="utf-8")
            (hw / "fan2_label").write_text("System Fan", encoding="utf-8")
            (hw / "pwm1").write_text("128", encoding="utf-8")
            (hw / "pwm1_enable").write_text("2", encoding="utf-8")
            (hw / "pwm2").write_text("80", encoding="utf-8")
            found: list[dict] = []
            paths: dict = {}
            _append_channel(found, paths, hw, "nct6775", 1, 1200)
            _append_channel(found, paths, hw, "nct6775", 2, 800)
            cpu, chassis = found
            self.assertEqual(cpu["label"], "CPU")
            self.assertEqual(cpu["role"], "cpu")
            self.assertTrue(cpu["controllable"])
            self.assertTrue(cpu["mode_controllable"])
            self.assertEqual(chassis["label"], "机箱")
            self.assertEqual(chassis["role"], "chassis")
            self.assertTrue(chassis["controllable"])
            self.assertFalse(chassis["mode_controllable"])
            if os.geteuid() != 0:
                os.chmod(hw / "pwm2", 0o444)
                found.clear()
                _append_channel(found, paths, hw, "nct6775", 2, 800)
                self.assertFalse(found[0]["controllable"])


class HistoryWindowTest(unittest.TestCase):
    def test_step_one_keeps_each_second(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "m.db")
            base = datetime(2026, 1, 1, tzinfo=timezone.utc)
            points = []
            for i in range(5):
                ts = (base + timedelta(seconds=i)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                points.append((ts, "cpu.pct", float(i), None))
            store.insert_points(points)
            got = store.history("cpu.pct", points[0][0], points[-1][0], step_sec=1)
            self.assertEqual([row["value"] for row in got], [0, 1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
