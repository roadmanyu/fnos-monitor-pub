"""分级刷新默认值、app_kv 覆盖、硬盘插拔去抖。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.collectors.presence import DiskPresenceDebounce
from app.config import AppConfig
from app.storage.sqlite_store import Store
from app.tuning import apply_stored_tuning, capture_baseline, clear_tuning, save_tuning


def _store() -> Store:
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "monitor.db"
    store = Store(path)
    store._tmp = tmp  # type: ignore[attr-defined]
    return store


class RefreshDefaultsTest(unittest.TestCase):
    def test_fast_overview_and_slower_disk(self):
        cfg = AppConfig()
        self.assertEqual(cfg.collect.interval_sec, 1)
        self.assertEqual(cfg.collect.fs_interval_sec, 60)
        self.assertEqual(cfg.collect.disk_plug_debounce_sec, 8)
        self.assertEqual(cfg.smart.interval_sec, 900)
        self.assertEqual(cfg.display.refresh.overview_sec, 1)
        self.assertEqual(cfg.display.refresh.disk_sec, 60)
        self.assertEqual(cfg.display.refresh.smart_sec, 60)


class TuningStoreTest(unittest.TestCase):
    def test_override_persists_and_reset_returns_to_config(self):
        cfg = AppConfig()
        capture_baseline(cfg, force=True)
        store = _store()
        saved = save_tuning(
            cfg,
            store,
            {
                "smart.interval_sec": 120,
                "collect.disk_plug_debounce_sec": 12,
                "display.refresh.overview_sec": 2,
                "smart.skip_standby": False,
            },
        )
        by_key = {item["key"]: item for item in saved["items"]}
        self.assertEqual(cfg.smart.interval_sec, 120)
        self.assertEqual(by_key["smart.interval_sec"]["source"], "db")
        self.assertEqual(by_key["smart.interval_sec"]["config"], 900)
        self.assertFalse(cfg.smart.skip_standby)

        restored = AppConfig()
        capture_baseline(restored, force=True)
        apply_stored_tuning(restored, store)
        self.assertEqual(restored.smart.interval_sec, 120)
        self.assertEqual(restored.collect.disk_plug_debounce_sec, 12)
        self.assertEqual(restored.display.refresh.overview_sec, 2)
        self.assertFalse(restored.smart.skip_standby)

        cleared = clear_tuning(restored, store)
        self.assertEqual(restored.smart.interval_sec, 900)
        self.assertEqual(restored.collect.disk_plug_debounce_sec, 8)
        self.assertTrue(restored.smart.skip_standby)
        again = {item["key"]: item for item in cleared["items"]}
        self.assertEqual(again["smart.interval_sec"]["source"], "config")
        self.assertIsNone(store.get_kv("tune.smart.interval_sec"))

    def test_same_as_config_does_not_keep_a_row(self):
        cfg = AppConfig()
        capture_baseline(cfg, force=True)
        store = _store()
        save_tuning(cfg, store, {"smart.interval_sec": 900})
        self.assertIsNone(store.get_kv("tune.smart.interval_sec"))

    def test_rejects_out_of_range_and_unknown_keys(self):
        cfg = AppConfig()
        capture_baseline(cfg, force=True)
        store = _store()
        with self.assertRaises(ValueError):
            save_tuning(cfg, store, {"smart.interval_sec": 1})
        with self.assertRaises(ValueError):
            save_tuning(cfg, store, {"nope": 1})
        self.assertEqual(cfg.smart.interval_sec, 900)


class DiskPresenceTest(unittest.TestCase):
    def test_first_sample_is_accepted_and_same_set_stays_stable(self):
        presence = DiskPresenceDebounce()
        self.assertEqual(presence.consider(["sda"], 0, 8), "accept")
        self.assertEqual(presence.consider(["sdb", "sda"], 1, 8), "pending")
        self.assertEqual(presence.consider(["sda", "sdb"], 1.5, 8), "pending")
        self.assertEqual(presence.consider(["sda"], 2, 8), "stable")

    def test_plug_waits_for_debounce_then_accepts(self):
        presence = DiskPresenceDebounce()
        presence.consider(["sda"], 0, 8)
        self.assertEqual(presence.consider(["sda", "sdb"], 1, 8), "pending")
        self.assertEqual(presence.consider(["sda", "sdb"], 8.9, 8), "pending")
        self.assertEqual(presence.consider(["sda", "sdb"], 9, 8), "accept")
        self.assertEqual(presence.consider(["sda", "sdb"], 10, 8), "stable")

    def test_flap_restarts_the_timer(self):
        presence = DiskPresenceDebounce()
        presence.consider(["sda"], 0, 8)
        self.assertEqual(presence.consider(["sdb"], 1, 8), "pending")
        self.assertEqual(presence.consider(["sda"], 2, 8), "stable")
        self.assertEqual(presence.consider(["sdb"], 3, 8), "pending")
        self.assertEqual(presence.consider(["sdb"], 10, 8), "pending")
        self.assertEqual(presence.consider(["sdb"], 11, 8), "accept")

    def test_zero_debounce_accepts_immediately(self):
        presence = DiskPresenceDebounce()
        presence.consider(["sda"], 0, 0)
        self.assertEqual(presence.consider(["sdb"], 0.1, 0), "accept")


if __name__ == "__main__":
    unittest.main()
