# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Small SQLite store for the hosted service: the daily allowance ledger (open beta), the
certification cache, queries and ratings, and OAuth state. Lives in CERTIFIER_DATA_DIR (default ./data).

Days run midnight to midnight America/Los_Angeles. Allowance buckets are keyed by a daily-salted
hash (see hosted.Controls); the salt for each day is random and earlier days' salts are deleted."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data"
PACIFIC = ZoneInfo("America/Los_Angeles")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS allowance (day TEXT, bucket TEXT, spent REAL DEFAULT 0, reserved REAL DEFAULT 0,
                                      lookups INTEGER DEFAULT 0, cache_hits INTEGER DEFAULT 0,
                                      limit_hits INTEGER DEFAULT 0, PRIMARY KEY (day, bucket));
CREATE TABLE IF NOT EXISTS salts (day TEXT PRIMARY KEY, salt TEXT);
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, created_at TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS oauth (kind TEXT, key TEXT, payload TEXT, expires_at REAL, PRIMARY KEY (kind, key));
CREATE TABLE IF NOT EXISTS queries (id TEXT PRIMARY KEY, created_at TEXT, subject TEXT, query TEXT, entity_name TEXT,
                                    certified_count INTEGER, confidence INTEGER, cached INTEGER, cost_usd REAL,
                                    record TEXT);
CREATE TABLE IF NOT EXISTS ratings (query_id TEXT, created_at TEXT, subject TEXT, rating TEXT, comment TEXT);
"""


def data_dir() -> Path:
    return Path(os.environ.get("CERTIFIER_DATA_DIR") or DEFAULT_DIR)


class Store:
    def __init__(self, path: Path | None = None, clock: Callable[[], datetime] | None = None):
        self.path = path or data_dir() / "certifier.sqlite3"
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # --- daily allowance ledger (open beta) ----------------------------------------------------

    def today(self) -> str:
        """Today in America/Los_Angeles: allowances reset at midnight Pacific."""
        return self.clock().astimezone(PACIFIC).date().isoformat()

    def salt(self) -> str:
        """Today's random salt for visitor hashes; earlier days' salts are deleted (rotated daily)."""
        day = self.today()
        with self._lock, self._conn() as c:
            row = c.execute("SELECT salt FROM salts WHERE day=?", (day,)).fetchone()
            if row:
                return row["salt"]
            salt = secrets.token_hex(32)
            c.execute("DELETE FROM salts WHERE day <> ?", (day,))
            c.execute("INSERT INTO salts (day, salt) VALUES (?, ?)", (day, salt))
            return salt

    def secret(self) -> str:
        """Server secret for keyed IP hashes (CERTIFIER_HASH_SECRET, else generated once and kept here)."""
        if os.environ.get("CERTIFIER_HASH_SECRET"):
            return os.environ["CERTIFIER_HASH_SECRET"]
        found = self.get("secret", "ip")
        if found:
            return found["value"]
        value = secrets.token_hex(32)
        self.put("secret", "ip", {"value": value})
        return value

    def reserve(self, bucket: str, amount: float, bucket_cap: float | None, global_cap: float | None) -> str | None:
        """Atomically reserve `amount` for today against the bucket's and the global allowance.
        Returns None when reserved, else "visitor" or "global" for the cap that would be exceeded.
        Spent plus reserved never passes either cap (None = no cap, e.g. admin)."""
        day = self.today()
        with self._lock:
            conn = self._conn()
            conn.isolation_level = None
            try:
                conn.execute("BEGIN IMMEDIATE")
                mine = conn.execute("SELECT COALESCE(SUM(spent + reserved), 0) FROM allowance WHERE day=? AND bucket=?",
                                    (day, bucket)).fetchone()[0]
                total = conn.execute("SELECT COALESCE(SUM(spent + reserved), 0) FROM allowance WHERE day=?",
                                     (day,)).fetchone()[0]
                reason = ("visitor" if bucket_cap is not None and mine + amount > bucket_cap + 1e-9 else
                          "global" if global_cap is not None and total + amount > global_cap + 1e-9 else None)
                if reason:
                    conn.execute("INSERT INTO allowance (day, bucket, limit_hits) VALUES (?, ?, 1) ON CONFLICT(day, bucket) "
                                 "DO UPDATE SET limit_hits = limit_hits + 1", (day, bucket))
                else:
                    conn.execute("INSERT INTO allowance (day, bucket, reserved) VALUES (?, ?, ?) ON CONFLICT(day, bucket) "
                                 "DO UPDATE SET reserved = reserved + excluded.reserved", (day, bucket, amount))
                conn.execute("COMMIT")
                return reason
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def settle(self, bucket: str, reserved: float, actual: float, lookups: int = 0) -> None:
        """Release a reservation and record what was actually spent."""
        day = self.today()
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO allowance (day, bucket, spent, lookups) VALUES (?, ?, ?, ?) ON CONFLICT(day, bucket) "
                      "DO UPDATE SET reserved = MAX(0, reserved - ?), spent = spent + excluded.spent, "
                      "lookups = lookups + excluded.lookups", (day, bucket, actual, lookups, reserved))

    def note_cache_hit(self, bucket: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO allowance (day, bucket, cache_hits) VALUES (?, ?, 1) ON CONFLICT(day, bucket) "
                      "DO UPDATE SET cache_hits = cache_hits + 1", (self.today(), bucket))

    def used(self, bucket: str) -> tuple[float, float]:
        """(this bucket's spent + reserved, everyone's spent + reserved) today."""
        day = self.today()
        with self._lock, self._conn() as c:
            mine = c.execute("SELECT COALESCE(SUM(spent + reserved), 0) FROM allowance WHERE day=? AND bucket=?",
                             (day, bucket)).fetchone()[0]
            total = c.execute("SELECT COALESCE(SUM(spent + reserved), 0) FROM allowance WHERE day=?", (day,)).fetchone()[0]
        return float(mine), float(total)

    def spend_today(self) -> float:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT COALESCE(SUM(spent), 0) AS usd FROM allowance WHERE day=?", (self.today(),)).fetchone()
        return float(row["usd"])

    def summary_today(self) -> dict:
        """Admin view of today: spend, lookups, cache hits, distinct visitors, limit hits."""
        with self._lock, self._conn() as c:
            row = c.execute("SELECT COALESCE(SUM(spent), 0) AS spent, COALESCE(SUM(reserved), 0) AS reserved, "
                            "COALESCE(SUM(lookups), 0) AS lookups, COALESCE(SUM(cache_hits), 0) AS cache_hits, "
                            "COALESCE(SUM(limit_hits), 0) AS limit_hits, "
                            "COUNT(DISTINCT CASE WHEN bucket LIKE 'v:%' THEN bucket END) AS visitors "
                            "FROM allowance WHERE day=?", (self.today(),)).fetchone()
        return {"day": self.today(), **{k: row[k] for k in row.keys()}}

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

    # --- queries, results and ratings (review queue) -----------------------------------------

    def save_query(self, query_id: str, subject: str, query: str, entity_name: str, certified_count: int | None,
                   confidence: int, cached: bool, cost_usd: float, record_json: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO queries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (query_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), subject, query, entity_name,
                       certified_count, confidence, int(cached), cost_usd, record_json))

    def get_query(self, query_id: str) -> dict | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT * FROM queries WHERE id=?", (query_id,)).fetchone()
        return dict(row) if row else None

    def save_rating(self, query_id: str, subject: str, rating: str, comment: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO ratings VALUES (?, ?, ?, ?, ?)",
                      (query_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), subject, rating, comment))

    def ratings(self, limit: int = 100) -> list[dict]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT r.*, q.query, q.entity_name, q.certified_count, q.confidence FROM ratings r "
                             "LEFT JOIN queries q ON q.id = r.query_id ORDER BY r.created_at DESC LIMIT ?",
                             (limit,)).fetchall()
        return [dict(r) for r in rows]

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
