"""SQLite 存储。"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Store:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS metric_points (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts TEXT NOT NULL,
              metric TEXT NOT NULL,
              value REAL NOT NULL,
              labels_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_metric_ts ON metric_points(metric, ts);

            CREATE TABLE IF NOT EXISTS alert_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts TEXT NOT NULL,
              rule_id TEXT NOT NULL,
              severity TEXT NOT NULL,
              title TEXT NOT NULL,
              message TEXT NOT NULL,
              fingerprint TEXT NOT NULL,
              notified INTEGER NOT NULL DEFAULT 0,
              acked INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_alert_fp_ts ON alert_events(fingerprint, ts);

            CREATE TABLE IF NOT EXISTS disk_calibration (
              identity_key TEXT PRIMARY KEY,
              serial TEXT NOT NULL DEFAULT '',
              wwn TEXT NOT NULL DEFAULT '',
              visible INTEGER NOT NULL DEFAULT 1,
              label TEXT NOT NULL DEFAULT '',
              role TEXT NOT NULL DEFAULT '',
              media TEXT NOT NULL DEFAULT '',
              interface TEXT NOT NULL DEFAULT '',
              sort_order INTEGER NOT NULL DEFAULT 0,
              updated_ts TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS fan_channel_map (
              channel_key TEXT PRIMARY KEY,
              fan_id TEXT NOT NULL DEFAULT '',
              role TEXT NOT NULL DEFAULT '',
              primary_display INTEGER NOT NULL DEFAULT 0,
              excluded INTEGER NOT NULL DEFAULT 0,
              updated_ts TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_kv (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def insert_points(self, points: list[tuple[str, str, float, dict | None]]) -> None:
        with self._lock:
            self._insert_points(points)

    def _insert_points(self, points: list[tuple[str, str, float, dict | None]]) -> None:
        cur = self._conn.cursor()
        cur.executemany(
            "INSERT INTO metric_points(ts, metric, value, labels_json) VALUES (?,?,?,?)",
            [
                (ts, metric, value, json.dumps(labels) if labels else None)
                for ts, metric, value, labels in points
            ],
        )
        self._conn.commit()

    def history(
        self, metric: str, from_ts: str, to_ts: str, step_sec: int = 60
    ) -> list[dict[str, Any]]:
        with self._lock:
            return self._history(metric, from_ts, to_ts, step_sec)

    def _history(
        self, metric: str, from_ts: str, to_ts: str, step_sec: int = 60
    ) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        rows = cur.execute(
            """
            SELECT ts, value FROM metric_points
            WHERE metric = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
            """,
            (metric, from_ts, to_ts),
        ).fetchall()
        if not rows:
            return []
        # 简单降采样：按 step 桶取最后一个点
        if step_sec <= 0:
            return [{"ts": r["ts"], "value": r["value"]} for r in rows]
        out: list[dict[str, Any]] = []
        bucket = None
        last = None
        for r in rows:
            # 粗略按字符串秒对齐不够严谨，用 epoch
            try:
                dt = datetime.fromisoformat(r["ts"].replace("Z", "+00:00"))
                epoch = int(dt.timestamp())
            except Exception:
                continue
            b = epoch // step_sec
            if bucket is None:
                bucket = b
            if b != bucket:
                if last:
                    out.append(last)
                bucket = b
            last = {"ts": r["ts"], "value": r["value"]}
        if last:
            out.append(last)
        return out

    def insert_alert(
        self,
        rule_id: str,
        severity: str,
        title: str,
        message: str,
        fingerprint: str,
        notified: bool,
    ) -> int:
        with self._lock:
            return self._insert_alert(rule_id, severity, title, message, fingerprint, notified)

    def _insert_alert(
        self,
        rule_id: str,
        severity: str,
        title: str,
        message: str,
        fingerprint: str,
        notified: bool,
    ) -> int:
        ts = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO alert_events(ts, rule_id, severity, title, message, fingerprint, notified, acked)
            VALUES (?,?,?,?,?,?,?,0)
            """,
            (ts, rule_id, severity, title, message, fingerprint, 1 if notified else 0),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def last_alert_ts(self, fingerprint: str) -> str | None:
        with self._lock:
            return self._last_alert_ts(fingerprint)

    def _last_alert_ts(self, fingerprint: str) -> str | None:
        row = self._conn.execute(
            "SELECT ts FROM alert_events WHERE fingerprint = ? ORDER BY id DESC LIMIT 1",
            (fingerprint,),
        ).fetchone()
        return row["ts"] if row else None

    def list_alerts(self, limit: int = 50, severity: str | None = None) -> list[dict]:
        with self._lock:
            return self._list_alerts(limit, severity)

    def _list_alerts(self, limit: int = 50, severity: str | None = None) -> list[dict]:
        if severity:
            rows = self._conn.execute(
                """
                SELECT * FROM alert_events WHERE severity = ?
                ORDER BY id DESC LIMIT ?
                """,
                (severity, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM alert_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {
                "id": r["id"],
                "ts": r["ts"],
                "rule_id": r["rule_id"],
                "severity": r["severity"],
                "title": r["title"],
                "message": r["message"],
                "notified": bool(r["notified"]),
                "acked": bool(r["acked"]),
            }
            for r in rows
        ]

    def ack_alert(self, alert_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
            "UPDATE alert_events SET acked = 1 WHERE id = ?", (alert_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def cleanup(self, retention_days: int, alert_days: int = 30) -> None:
        with self._lock:
            self._cleanup(retention_days, alert_days)

    def _cleanup(self, retention_days: int, alert_days: int = 30) -> None:
        now = datetime.now(timezone.utc)
        metric_cut = (now - timedelta(days=retention_days)).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
        alert_cut = (now - timedelta(days=alert_days)).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
        self._conn.execute("DELETE FROM metric_points WHERE ts < ?", (metric_cut,))
        self._conn.execute("DELETE FROM alert_events WHERE ts < ?", (alert_cut,))
        self._conn.commit()

    def get_kv(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM app_kv WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def set_kv(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO app_kv(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            self._conn.commit()

    def delete_kv(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM app_kv WHERE key = ?", (key,))
            self._conn.commit()

    def list_disk_calibrations(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM disk_calibration ORDER BY sort_order, identity_key"
            ).fetchall()
        return [self._disk_row(row) for row in rows]

    def upsert_disk_calibrations(self, items: list[dict[str, Any]]) -> None:
        ts = _utc_now()
        with self._lock:
            for item in items:
                self._conn.execute(
                    """
                    INSERT INTO disk_calibration(
                      identity_key, serial, wwn, visible, label, role, media, interface, sort_order, updated_ts
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(identity_key) DO UPDATE SET
                      serial = excluded.serial,
                      wwn = excluded.wwn,
                      visible = excluded.visible,
                      label = excluded.label,
                      role = excluded.role,
                      media = excluded.media,
                      interface = excluded.interface,
                      sort_order = excluded.sort_order,
                      updated_ts = excluded.updated_ts
                    """,
                    (
                        item["identity_key"],
                        item.get("serial") or "",
                        item.get("wwn") or "",
                        1 if item.get("visible", True) else 0,
                        item.get("label") or "",
                        item.get("role") or "",
                        item.get("media") or "",
                        item.get("interface") or "",
                        int(item.get("sort_order") or 0),
                        ts,
                    ),
                )
            self._conn.commit()

    def list_fan_maps(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM fan_channel_map ORDER BY channel_key"
            ).fetchall()
        return [self._fan_row(row) for row in rows]

    def upsert_fan_maps(self, items: list[dict[str, Any]]) -> None:
        ts = _utc_now()
        with self._lock:
            for item in items:
                self._conn.execute(
                    """
                    INSERT INTO fan_channel_map(
                      channel_key, fan_id, role, primary_display, excluded, updated_ts
                    ) VALUES (?,?,?,?,?,?)
                    ON CONFLICT(channel_key) DO UPDATE SET
                      fan_id = excluded.fan_id,
                      role = excluded.role,
                      primary_display = excluded.primary_display,
                      excluded = excluded.excluded,
                      updated_ts = excluded.updated_ts
                    """,
                    (
                        item["channel_key"],
                        item.get("fan_id") or "",
                        item.get("role") or "",
                        1 if item.get("primary") else 0,
                        1 if item.get("excluded") else 0,
                        ts,
                    ),
                )
            if any(item.get("primary") for item in items):
                keys = [item["channel_key"] for item in items if item.get("primary")]
                marks = ",".join("?" for _ in keys)
                self._conn.execute(
                    f"UPDATE fan_channel_map SET primary_display = 0 WHERE channel_key NOT IN ({marks})",
                    keys,
                )
            self._conn.commit()

    @staticmethod
    def _disk_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "identity_key": row["identity_key"],
            "serial": row["serial"],
            "wwn": row["wwn"],
            "visible": bool(row["visible"]),
            "label": row["label"],
            "role": row["role"],
            "media": row["media"],
            "interface": row["interface"],
            "sort_order": int(row["sort_order"]),
        }

    @staticmethod
    def _fan_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "channel_key": row["channel_key"],
            "fan_id": row["fan_id"],
            "role": row["role"],
            "primary": bool(row["primary_display"]),
            "excluded": bool(row["excluded"]),
        }
