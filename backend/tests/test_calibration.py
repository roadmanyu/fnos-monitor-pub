"""磁盘身份、容量口径、风扇映射、隐藏与排序。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.calibration import (
    apply_disk_calibration,
    apply_fan_mapping,
    disk_identity,
    fan_channel_key,
    format_capacity,
    match_disk_calibration,
    read_block_identity,
    visible_disks,
)
from app.config import AppConfig
from app.storage.sqlite_store import Store


class IdentityTest(unittest.TestCase):
    def test_serial_and_wwn_normalize(self):
        got = disk_identity(serial="WD-WC AY123", wwn="0x5000c500abc", device="/dev/sda")
        self.assertTrue(got["identity_stable"])
        self.assertEqual(got["serial"], "WDWCAY123")
        self.assertEqual(got["wwn"], "5000C500ABC")
        self.assertEqual(got["identity_key"], "sn:WDWCAY123|wwn:5000C500ABC")

    def test_serial_only_and_wwn_only(self):
        serial_only = disk_identity(serial="ABC", wwn="", device="sda")
        wwn_only = disk_identity(serial="", wwn="naa.5000cca", device="sdb")
        self.assertEqual(serial_only["identity_key"], "sn:ABC")
        self.assertEqual(wwn_only["identity_key"], "wwn:5000CCA")
        self.assertTrue(serial_only["identity_stable"])
        self.assertTrue(wwn_only["identity_stable"])

    def test_missing_identity_falls_back_to_device_and_does_not_match_another_name(self):
        sda = disk_identity(serial="", wwn=None, device="sda")
        sdb = disk_identity(serial="", wwn="", device="sdb")
        self.assertEqual(sda["identity_key"], "dev:sda")
        self.assertFalse(sda["identity_stable"])
        self.assertNotEqual(sda["identity_key"], sdb["identity_key"])

    def test_replug_matches_serial_when_wwn_or_name_changes(self):
        stored = {
            "identity_key": "sn:ABC|wwn:5000",
            "serial": "ABC",
            "wwn": "5000",
            "visible": 0,
            "label": "仓库",
            "role": "vol1",
            "media": "",
            "interface": "",
            "sort_order": 0,
        }
        replugged = {
            "id": "sdc",
            "serial": "ABC",
            "wwn": "",
            "role": "系统盘",
            "media": "SATA HDD",
        }
        self.assertEqual(match_disk_calibration(
            disk_identity(serial="ABC", wwn="", device="sdc") | replugged,
            [stored],
        )["label"], "仓库")
        applied = apply_disk_calibration([replugged], [stored])
        self.assertEqual(applied[0]["display_name"], "仓库")
        self.assertFalse(applied[0]["visible"])
        self.assertEqual(applied[0]["role"], "vol1")
        self.assertTrue(applied[0]["identity_stable"])

    def test_dev_fallback_does_not_claim_a_serialized_disk(self):
        stored = {
            "identity_key": "dev:sda",
            "serial": "",
            "wwn": "",
            "visible": 0,
            "label": "旧盘",
            "role": "",
            "media": "",
            "interface": "",
            "sort_order": 0,
        }
        moved = {"id": "sdb", "serial": "", "wwn": "", "role": None, "media": "SATA HDD"}
        applied = apply_disk_calibration([moved], [stored])
        self.assertTrue(applied[0]["visible"])
        self.assertEqual(applied[0]["display_name"], "sdb")
        self.assertEqual(applied[0]["label"], "")

    def test_sysfs_serial_and_wwn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            device = root / "sys" / "block" / "sda" / "device"
            device.mkdir(parents=True)
            (device / "serial").write_text("WD-123\n", encoding="utf-8")
            (device / "wwid").write_text("naa.5000c500aabbccdd\n", encoding="utf-8")
            by_id = root / "by-id"
            by_id.mkdir()
            target = root / "dev" / "sdb"
            target.parent.mkdir()
            target.write_text("", encoding="utf-8")
            (by_id / "wwn-0x5000c500ffff").symlink_to(target)
            serial, wwn = read_block_identity("sda", sys_root=root / "sys", by_id_root=by_id)
            self.assertEqual(serial, "WD-123")
            self.assertEqual(wwn, "naa.5000c500aabbccdd")
            (root / "sys" / "block" / "sdb" / "device").mkdir(parents=True)
            serial_b, wwn_b = read_block_identity("sdb", sys_root=root / "sys", by_id_root=by_id)
            self.assertEqual(serial_b, "")
            self.assertEqual(wwn_b, "0x5000c500ffff")


class HideSortTest(unittest.TestCase):
    def test_hide_sort_role_and_media(self):
        rows = [
            {
                "identity_key": "sn:A",
                "serial": "A",
                "wwn": "",
                "visible": 0,
                "label": "",
                "role": "",
                "media": "",
                "interface": "",
                "sort_order": 0,
            },
            {
                "identity_key": "sn:B",
                "serial": "B",
                "wwn": "",
                "visible": 1,
                "label": "缓存盘",
                "role": "缓存",
                "media": "SSD",
                "interface": "NVMe",
                "sort_order": 5,
            },
            {
                "identity_key": "sn:C",
                "serial": "C",
                "wwn": "",
                "visible": 1,
                "label": "",
                "role": "none",
                "media": "",
                "interface": "",
                "sort_order": 1,
            },
        ]
        disks = [
            {"id": "sda", "serial": "A", "wwn": "", "role": "系统盘", "media": "SATA HDD"},
            {"id": "sdb", "serial": "B", "wwn": "", "role": None, "media": "NVMe"},
            {"id": "sdc", "serial": "C", "wwn": "", "role": "vol1", "media": "SATA HDD"},
        ]
        out = apply_disk_calibration(disks, rows)
        self.assertEqual([disk["id"] for disk in out], ["sda", "sdc", "sdb"])
        self.assertFalse(out[0]["visible"])
        self.assertEqual(out[0]["role"], "系统盘")
        self.assertIsNone(out[1]["role"])
        self.assertEqual(out[1]["role_override"], "none")
        self.assertEqual(out[2]["display_name"], "缓存盘")
        self.assertEqual(out[2]["role"], "缓存")
        self.assertEqual(out[2]["media"], "NVMe SSD")
        shown = visible_disks(out)
        self.assertEqual([disk["id"] for disk in shown], ["sdc", "sdb"])

    def test_sqlite_roundtrip_keeps_identity_after_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "m.db")
            store.upsert_disk_calibrations([
                {
                    "identity_key": "sn:ABC|wwn:5000",
                    "serial": "ABC",
                    "wwn": "5000",
                    "visible": False,
                    "label": "仓库",
                    "role": "vol1",
                    "media": "",
                    "interface": "SATA",
                    "sort_order": 3,
                }
            ])
            rows = store.list_disk_calibrations()
            applied = apply_disk_calibration(
                [{"id": "sdz", "serial": "ABC", "wwn": "5000", "role": None, "media": "SATA HDD"}],
                rows,
            )
            self.assertEqual(applied[0]["label"], "仓库")
            self.assertFalse(applied[0]["visible"])
            self.assertEqual(applied[0]["sort_order"], 3)
            self.assertEqual(applied[0]["interface"], "SATA")


class FanMappingTest(unittest.TestCase):
    def _fans(self):
        return [
            {
                "id": "hwmon1:fan1",
                "chip": "nct6775",
                "raw_label": "CPU Fan",
                "label": "CPU",
                "role": "cpu",
                "rpm": 1000,
                "controllable": True,
                "mode_controllable": True,
            },
            {
                "id": "hwmon1:fan2",
                "chip": "nct6775",
                "raw_label": "System",
                "label": "机箱",
                "role": "chassis",
                "rpm": 800,
                "controllable": False,
                "mode_controllable": False,
            },
            {
                "id": "hwmon1:fan3",
                "chip": "nct6775",
                "raw_label": "fan3",
                "label": "fan3",
                "role": "other",
                "rpm": 100,
                "controllable": False,
                "mode_controllable": False,
            },
        ]

    def test_mapping_sets_role_primary_and_drops_excluded(self):
        fans = self._fans()
        maps = [
            {
                "channel_key": fan_channel_key(fans[0]),
                "fan_id": "hwmon1:fan1",
                "role": "",
                "primary": False,
                "excluded": True,
            },
            {
                "channel_key": fan_channel_key(fans[2]),
                "fan_id": "hwmon1:fan3",
                "role": "cpu",
                "primary": True,
                "excluded": False,
            },
        ]
        out = apply_fan_mapping(fans, maps, drop_excluded=True)
        self.assertEqual([fan["id"] for fan in out], ["hwmon1:fan2", "hwmon1:fan3"])
        cpu = out[1]
        self.assertEqual(cpu["role"], "cpu")
        self.assertEqual(cpu["label"], "CPU")
        self.assertTrue(cpu["primary"])
        self.assertFalse(cpu["controllable"])
        self.assertFalse(out[0]["controllable"])
        self.assertFalse(out[0]["primary"])

    def test_hwmon_number_change_still_matches_chip_and_index(self):
        moved = {
            "id": "hwmon7:fan1",
            "chip": "nct6775",
            "raw_label": "CPU Fan",
            "label": "CPU",
            "role": "cpu",
            "controllable": False,
        }
        key = fan_channel_key({"id": "hwmon1:fan1", "chip": "nct6775", "raw_label": "CPU Fan"})
        out = apply_fan_mapping(
            [moved],
            [{"channel_key": key, "fan_id": "hwmon1:fan1", "role": "chassis", "primary": True, "excluded": False}],
        )
        self.assertEqual(out[0]["role"], "chassis")
        self.assertEqual(out[0]["label"], "机箱")
        self.assertTrue(out[0]["primary"])
        self.assertFalse(out[0]["controllable"])

    def test_excluded_stays_visible_for_settings(self):
        fans = self._fans()
        key = fan_channel_key(fans[1])
        out = apply_fan_mapping(
            fans,
            [{"channel_key": key, "fan_id": fans[1]["id"], "role": "chassis", "primary": False, "excluded": True}],
            drop_excluded=False,
        )
        self.assertEqual(len(out), 3)
        self.assertTrue(out[1]["excluded"])


class CapacityFormatterTest(unittest.TestCase):
    def test_units_and_label_fallback(self):
        drive = 4000787030016
        label = 4_000_000_000_000
        self.assertEqual(format_capacity(drive, "gib", 1), "3.6 TiB")
        self.assertEqual(format_capacity(drive, "gb", 2), "4.00 TB")
        self.assertEqual(format_capacity(drive, "label", 0, label), "4 TB")
        self.assertEqual(format_capacity(drive, "label", 1, None), "3.6 TiB")
        self.assertEqual(format_capacity(None, "gib", 1), "—")
        self.assertEqual(format_capacity(512, "gb", 2), "512 B")

    def test_config_default_unit(self):
        cfg = AppConfig()
        self.assertEqual(cfg.display.capacity.unit, "gib")
        self.assertEqual(cfg.display.capacity.decimals, 1)
        self.assertTrue(cfg.fans.control_enabled)


if __name__ == "__main__":
    unittest.main()
