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
