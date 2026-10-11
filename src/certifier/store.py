"""Small SQLite store for the hosted service: daily usage (spend controls), the certification
cache, and OAuth state. Lives in CERTIFIER_DATA_DIR (default ./data)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (day TEXT, subject TEXT, lookups INTEGER DEFAULT 0, usd REAL DEFAULT 0,
                                  PRIMARY KEY (day, subject));
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, created_at TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS oauth (kind TEXT, key TEXT, payload TEXT, expires_at REAL, PRIMARY KEY (kind, key));
"""


def data_dir() -> Path:
    return Path(os.environ.get("CERTIFIER_DATA_DIR") or DEFAULT_DIR)


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "certifier.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # --- usage --------------------------------------------------------------------------------

    @staticmethod
    def today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def lookups_today(self, subject: str) -> int:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT lookups FROM usage WHERE day=? AND subject=?", (self.today(), subject)).fetchone()
        return row["lookups"] if row else 0

    def spend_today(self) -> float:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT COALESCE(SUM(usd), 0) AS usd FROM usage WHERE day=?", (self.today(),)).fetchone()
        return float(row["usd"])

    def record_usage(self, subject: str, lookups: int, usd: float) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO usage (day, subject, lookups, usd) VALUES (?, ?, ?, ?) "
                      "ON CONFLICT(day, subject) DO UPDATE SET lookups = lookups + excluded.lookups, "
                      "usd = usd + excluded.usd", (self.today(), subject, lookups, usd))

    # --- certification cache ------------------------------------------------------------------

    def cache_get(self, key: str, max_age_days: int) -> tuple[str, datetime] | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT created_at, payload FROM cache WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        created = datetime.fromisoformat(row["created_at"])
        if datetime.now(timezone.utc) - created > timedelta(days=max_age_days):
            return None
        return row["payload"], created

    def cache_put(self, key: str, payload: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO cache (key, created_at, payload) VALUES (?, ?, ?)",
                      (key, datetime.now(timezone.utc).isoformat(timespec="seconds"), payload))

    # --- OAuth state --------------------------------------------------------------------------

    def put(self, kind: str, key: str, payload: dict, ttl_seconds: float | None = None) -> None:
        expires = time.time() + ttl_seconds if ttl_seconds else None
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO oauth (kind, key, payload, expires_at) VALUES (?, ?, ?, ?)",
                      (kind, key, json.dumps(payload, default=str), expires))

    def get(self, kind: str, key: str) -> dict | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT payload, expires_at FROM oauth WHERE kind=? AND key=?", (kind, key)).fetchone()
        if not row or (row["expires_at"] is not None and row["expires_at"] < time.time()):
            return None
        return json.loads(row["payload"])

    def delete(self, kind: str, key: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM oauth WHERE kind=? AND key=?", (kind, key))
