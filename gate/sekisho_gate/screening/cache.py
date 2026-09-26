"""Intercepta response cache and request counter (PRD 9.3, 9.14).

Two tables in the gate's SQLite file (`settings.db_path`), created if missing:

- `intercepta_cache(endpoint, address, response_json, fetched_at)`, primary key
  `(endpoint, address)`. `response_json` is the response body text exactly as received,
  `fetched_at` is Unix seconds.
- `quota(name, value)`: counters. `intercepta_calls` counts every HTTP call made to
  Intercepta, successful or not.

Stdlib sqlite3 in WAL mode, one short-lived connection per operation, so the gate's
store can share the file.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

CACHE_TTL_S = 24 * 3600
QUOTA_KEY = "intercepta_calls"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS intercepta_cache (
    endpoint TEXT NOT NULL,
    address TEXT NOT NULL,
    response_json TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    PRIMARY KEY (endpoint, address)
);
CREATE TABLE IF NOT EXISTS quota (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);
"""


class InterceptaCache:
    """Cache reads and writes plus the quota counter. Addresses are stored lowercased."""

    def __init__(
        self,
        db_path: Path | str,
        ttl_s: float = CACHE_TTL_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db_path = Path(db_path)
        self.ttl_s = ttl_s
        self._clock = clock
        self._lock = threading.Lock()  # serialises read-modify-write on the counter
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """A connection that commits on success, rolls back on error, and always closes."""
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ---------- cache ----------

    def get(self, endpoint: str, address: str) -> str | None:
        """The cached body if it is younger than the TTL, else None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT response_json, fetched_at FROM intercepta_cache"
                " WHERE endpoint = ? AND address = ?",
                (endpoint, address.lower()),
            ).fetchone()
        if row is None:
            return None
        body, fetched_at = row
        if self._clock() - float(fetched_at) >= self.ttl_s:
            return None
        return body

    def put(self, endpoint: str, address: str, response_json: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO intercepta_cache (endpoint, address, response_json, fetched_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT (endpoint, address) DO UPDATE SET"
                " response_json = excluded.response_json, fetched_at = excluded.fetched_at",
                (endpoint, address.lower(), response_json, self._clock()),
            )

    # ---------- counters ----------

    def incr(self, name: str = QUOTA_KEY, by: int = 1) -> int:
        """Add `by` to a counter and return the new value."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO quota (name, value) VALUES (?, ?)"
                " ON CONFLICT (name) DO UPDATE SET value = value + excluded.value",
                (name, by),
            )
            row = conn.execute("SELECT value FROM quota WHERE name = ?", (name,)).fetchone()
        return int(row[0])

    def value(self, name: str = QUOTA_KEY) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM quota WHERE name = ?", (name,)).fetchone()
        return int(row[0]) if row else 0
