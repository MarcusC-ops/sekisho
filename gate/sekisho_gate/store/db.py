"""SQLite case store (PRD 9.14): stdlib sqlite3, WAL, one connection behind a lock.

Tables here: cases, checks, reports, chain_events, officer_overrides, audit_log and
idempotency. `intercepta_cache` and `quota` live in the same file but belong to
screening/cache.py.

Mutable case state (attestation, analyst note, hold, payment, status) lives in columns;
`decision_json` keeps the decision exactly as it was made.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..errors import invalid_state
from ..policy.engine import Override
from ..util import iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id            TEXT PRIMARY KEY,
    case_id_b32        TEXT NOT NULL UNIQUE,
    created_at         TEXT NOT NULL,
    created_ts         REAL NOT NULL,
    direction          TEXT NOT NULL,
    counterparty       TEXT NOT NULL,
    amount             TEXT NOT NULL,
    amount_usd         REAL NOT NULL DEFAULT 0,
    asset              TEXT NOT NULL,
    payment_chain_id   INTEGER,
    source             TEXT,
    agent_id           TEXT,
    purpose            TEXT,
    resource           TEXT,
    untrusted_context  TEXT,
    verdict            TEXT NOT NULL,
    risk_score         INTEGER NOT NULL,
    status             TEXT NOT NULL,
    report_hash        TEXT NOT NULL,
    policy_id          TEXT NOT NULL,
    decision_json      TEXT NOT NULL,
    evidence_json      TEXT,
    deep_scan_json     TEXT,
    analyst_json       TEXT,
    attestation_status TEXT NOT NULL DEFAULT 'queued',
    attestation_tx     TEXT,
    attestation_error  TEXT,
    payment_tx         TEXT,
    payment_network    TEXT,
    hold_id            INTEGER,
    hold_status        TEXT,
    deposit_tx         TEXT,
    override_tx        TEXT,
    action_tx          TEXT,
    officer_note       TEXT,
    latency_ms         INTEGER,
    decided_at         TEXT,
    updated_at         TEXT,
    archived           INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cases_counterparty ON cases(counterparty);
CREATE INDEX IF NOT EXISTS idx_cases_archived ON cases(archived, case_id);

CREATE TABLE IF NOT EXISTS checks (
    check_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL,
    latency_ms  INTEGER,
    live        INTEGER,
    summary     TEXT,
    error       TEXT,
    evidence_id TEXT,
    data_json   TEXT,
    raw_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_checks_case ON checks(case_id);

CREATE TABLE IF NOT EXISTS reports (
    report_hash     TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL,
    canonical_bytes BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS chain_events (
    event_uid        TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    contract_alias   TEXT,
    contract_address TEXT,
    tx_hash          TEXT,
    block_number     INTEGER,
    log_index        INTEGER,
    inputs_json      TEXT,
    case_id          TEXT,
    case_id_b32      TEXT,
    source           TEXT,
    received_at      TEXT NOT NULL,
    received_ts      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_case_b32 ON chain_events(case_id_b32);

CREATE TABLE IF NOT EXISTS officer_overrides (
    counterparty TEXT PRIMARY KEY,
    verdict      TEXT NOT NULL,
    expires_at   INTEGER NOT NULL,
    case_id      TEXT,
    tx_hash      TEXT,
    created_at   TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    case_id     TEXT,
    detail_json TEXT
);

CREATE TABLE IF NOT EXISTS idempotency (
    key        TEXT PRIMARY KEY,
    case_id    TEXT NOT NULL,
    created_ts REAL NOT NULL
);
"""

# Columns update_case() may write.
_MUTABLE = {
    "status",
    "evidence_json",
    "deep_scan_json",
    "analyst_json",
    "attestation_status",
    "attestation_tx",
    "attestation_error",
    "payment_tx",
    "payment_network",
    "hold_id",
    "hold_status",
    "deposit_tx",
    "override_tx",
    "action_tx",
    "officer_note",
}

# Attestation states: never go back from confirmed, never back to queued.
_ATTEST_RANK = {"queued": 0, "submitted": 1, "failed": 2, "confirmed": 3}


def dumps(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)


def loads(text: str | None) -> Any:
    return None if text is None else json.loads(text)


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def _one(self, sql: str, args: tuple = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, args).fetchone()
        return dict(row) if row is not None else None

    def _all(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    # ---------- cases ----------

    def insert_case(
        self,
        case: dict[str, Any],
        checks: list[dict[str, Any]],
        report_hash: str,
        report_bytes: bytes,
        idem_key: str | None = None,
        idem_ts: float | None = None,
    ) -> None:
        """Case, its checks, its report bytes and its idempotency key, atomically."""
        cols = list(case.keys())
        with self._tx() as c:
            c.execute(
                f"INSERT INTO cases ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                tuple(case[k] for k in cols),
            )
            for chk in checks:
                c.execute(
                    "INSERT INTO checks (case_id, name, status, latency_ms, live, summary, error,"
                    " evidence_id, data_json, raw_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        case["case_id"],
                        chk["name"],
                        chk["status"],
                        chk.get("latency_ms"),
                        None if chk.get("live") is None else int(bool(chk["live"])),
                        chk.get("summary"),
                        chk.get("error"),
                        chk.get("evidence_id"),
                        dumps(chk.get("data")),
                        dumps(chk.get("raw")),
                    ),
                )
            c.execute(
                "INSERT OR IGNORE INTO reports (report_hash, case_id, canonical_bytes) VALUES (?,?,?)",
                (report_hash, case["case_id"], sqlite3.Binary(report_bytes)),
            )
            if idem_key:
                c.execute(
                    "INSERT OR REPLACE INTO idempotency (key, case_id, created_ts) VALUES (?,?,?)",
                    (idem_key, case["case_id"], idem_ts if idem_ts is not None else time.time()),
                )

    def add_check(self, case_id: str, chk: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO checks (case_id, name, status, latency_ms, live, summary, error,"
                " evidence_id, data_json, raw_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    case_id,
                    chk["name"],
                    chk["status"],
                    chk.get("latency_ms"),
                    None if chk.get("live") is None else int(bool(chk["live"])),
                    chk.get("summary"),
                    chk.get("error"),
                    chk.get("evidence_id"),
                    dumps(chk.get("data")),
                    dumps(chk.get("raw")),
                ),
            )

    def get_checks(self, case_id: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM checks WHERE case_id = ? ORDER BY check_id", (case_id,))

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM cases WHERE case_id = ?", (case_id,))

    def get_case_by_b32(self, b32: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM cases WHERE case_id_b32 = ?", (b32.lower(),))

    def list_cases(
        self,
        *,
        verdict: str | None = None,
        status: str | None = None,
        direction: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Newest first, archived cases excluded. The cursor is the last case id seen
        (case ids are monotonic ULIDs)."""
        where, args = ["archived = 0"], []
        for col, val in (("verdict", verdict), ("status", status), ("direction", direction)):
            if val is not None:
                where.append(f"{col} = ?")
                args.append(val)
        if cursor:
            where.append("case_id < ?")
            args.append(cursor)
        rows = self._all(
            f"SELECT * FROM cases WHERE {' AND '.join(where)} ORDER BY case_id DESC LIMIT ?",
            (*args, limit + 1),
        )
        next_cursor = rows[limit - 1]["case_id"] if len(rows) > limit else None
        return rows[:limit], next_cursor

    def record_verified_payment(self, case_id: str, tx_hash: str, network: str) -> bool:
        """Atomically prevent receipt reuse, including cases archived by demo reset."""
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
            if row is None or row["verdict"] != "ALLOW" or row["direction"] != "outbound":
                raise invalid_state("only outbound ALLOW cases can be paid")
            other = conn.execute(
                "SELECT case_id FROM cases WHERE lower(payment_tx) = ? AND payment_network = ? AND case_id != ?",
                (tx_hash.lower(), network, case_id),
            ).fetchone()
            if other is not None:
                raise invalid_state("transaction already proves payment for another case")
            if row["status"] == "PAID" and row["payment_tx"] == tx_hash and row["payment_network"] == network:
                return False
            if row["status"] != "DECIDED":
                raise invalid_state(f"case status is {row['status']}")
            conn.execute(
                "UPDATE cases SET status='PAID', payment_tx=?, payment_network=?, updated_at=? WHERE case_id=?",
                (tx_hash, network, iso(), case_id),
            )
            return True

    def record_verified_hold(self, case_id: str, hold_id: int, tx_hash: str) -> str:
        """Keep later webhook state when it arrives during receipt verification."""
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
            if row is None or row["verdict"] != "HOLD" or row["direction"] != "outbound":
                raise invalid_state("only outbound HOLD cases have escrow deposits")
            if row["hold_id"] is not None and int(row["hold_id"]) != hold_id:
                raise invalid_state("case already linked to a different hold")
            if row["deposit_tx"] and row["deposit_tx"] != tx_hash:
                raise invalid_state("case already linked to a different deposit")
            if row["status"] not in ("DECIDED", "HELD_ESCROWED"):
                return row["status"]
            conn.execute(
                "UPDATE cases SET status='HELD_ESCROWED', hold_id=?, deposit_tx=?, "
                "hold_status=COALESCE(hold_status, 'HELD'), updated_at=? WHERE case_id=?",
                (hold_id, tx_hash, iso(), case_id),
            )
            return "HELD_ESCROWED"

    def update_case(self, case_id: str, **fields: Any) -> bool:
        bad = set(fields) - _MUTABLE
        if bad:
            raise ValueError(f"not updatable: {sorted(bad)}")
        if not fields:
            return False
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE cases SET {sets}, updated_at = ? WHERE case_id = ?",
                (*fields.values(), iso(), case_id),
            )
        return cur.rowcount > 0

    def set_attestation(
        self, case_id: str, status: str, *, tx_hash: str | None = None, error: str | None = None
    ) -> bool:
        """Move the attestation forward. Returns False (no change) if that would move it
        backwards (e.g. a late 'failed' after a webhook already confirmed it)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT attestation_status, attestation_tx FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
            if row is None:
                return False
            current = row["attestation_status"]
            if current == "confirmed" and status != "confirmed":
                return False
            if _ATTEST_RANK.get(status, 0) < _ATTEST_RANK.get(current, 0) and not (
                current == "failed" and status in ("submitted", "confirmed")
            ):
                return False
            self._conn.execute(
                "UPDATE cases SET attestation_status = ?, attestation_tx = COALESCE(?, attestation_tx),"
                " attestation_error = ?, updated_at = ? WHERE case_id = ?",
                (status, tx_hash, error if status == "failed" else None, iso(), case_id),
            )
        return True

    def has_prior_allow_or_paid(self, counterparty: str, exclude_case_id: str | None = None) -> bool:
        """Rule 12 history: any earlier, non-archived ALLOW or PAID case for this
        counterparty (either direction)."""
        row = self._one(
            "SELECT 1 AS hit FROM cases WHERE counterparty = ? AND archived = 0"
            " AND (verdict = 'ALLOW' OR status = 'PAID') AND case_id != ? LIMIT 1",
            (counterparty, exclude_case_id or ""),
        )
        return row is not None

    # ---------- officer overrides (rule 0) ----------

    def active_override(self, counterparty: str, now: float | None = None) -> Override | None:
        row = self._one(
            "SELECT * FROM officer_overrides WHERE counterparty = ? AND expires_at > ?",
            (counterparty, int(now if now is not None else time.time())),
        )
        if row is None:
            return None
        return Override(
            verdict=row["verdict"],
            expires_at=int(row["expires_at"]),
            case_id=row["case_id"],
            tx_hash=row["tx_hash"],
        )

    def put_override(
        self, counterparty: str, verdict: str, expires_at: int, case_id: str | None, tx_hash: str | None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO officer_overrides (counterparty, verdict, expires_at, case_id,"
                " tx_hash, created_at) VALUES (?,?,?,?,?,?)",
                (counterparty, verdict, int(expires_at), case_id, tx_hash, iso()),
            )

    # ---------- idempotency ----------

    def idempotent_case_id(self, key: str, window_s: float, now: float | None = None) -> str | None:
        now = now if now is not None else time.time()
        row = self._one(
            "SELECT case_id FROM idempotency WHERE key = ? AND created_ts >= ?", (key, now - window_s)
        )
        return row["case_id"] if row else None

    # ---------- reports ----------

    def report_case_id(self, report_hash: str) -> str | None:
        row = self._one("SELECT case_id FROM reports WHERE report_hash = ?", (report_hash.lower(),))
        return row["case_id"] if row else None

    def get_report(self, report_hash: str) -> bytes | None:
        row = self._one("SELECT canonical_bytes FROM reports WHERE report_hash = ?", (report_hash.lower(),))
        return bytes(row["canonical_bytes"]) if row else None

    # ---------- chain events ----------

    def upsert_chain_event(self, ev: dict[str, Any]) -> bool:
        """Insert once per event_uid (txHash:indexInLog). Returns True if new."""
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO chain_events (event_uid, name, contract_alias, contract_address,"
                " tx_hash, block_number, log_index, inputs_json, case_id, case_id_b32, source,"
                " received_at, received_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ev["event_uid"],
                    ev["name"],
                    ev.get("contract_alias"),
                    ev.get("contract_address"),
                    ev.get("tx_hash"),
                    ev.get("block_number"),
                    ev.get("log_index"),
                    dumps(ev.get("inputs") or {}),
                    ev.get("case_id"),
                    ev.get("case_id_b32"),
                    ev.get("source"),
                    ev.get("received_at") or iso(),
                    time.time(),
                ),
            )
            if cur.rowcount == 0 and ev.get("case_id"):
                # Known event, case resolved now: fill the link in.
                self._conn.execute(
                    "UPDATE chain_events SET case_id = ? WHERE event_uid = ? AND case_id IS NULL",
                    (ev["case_id"], ev["event_uid"]),
                )
        return cur.rowcount > 0

    def list_chain_events(self, *, limit: int = 100, case_id: str | None = None) -> list[dict[str, Any]]:
        if case_id:
            return self._all(
                "SELECT * FROM chain_events WHERE case_id = ? ORDER BY block_number DESC,"
                " log_index DESC, received_ts DESC LIMIT ?",
                (case_id, limit),
            )
        return self._all(
            "SELECT * FROM chain_events ORDER BY block_number DESC, log_index DESC,"
            " received_ts DESC LIMIT ?",
            (limit,),
        )

    def chain_events_for_case(self, case_id: str, case_id_b32: str) -> list[dict[str, Any]]:
        """Oldest first."""
        return self._all(
            "SELECT * FROM chain_events WHERE case_id = ? OR case_id_b32 = ?"
            " ORDER BY block_number, log_index, received_ts",
            (case_id, case_id_b32.lower()),
        )

    def has_chain_event(self, tx_hash: str) -> bool:
        return self._one("SELECT 1 AS hit FROM chain_events WHERE tx_hash = ? LIMIT 1", (tx_hash,)) is not None

    def last_webhook_ts(self) -> float | None:
        row = self._one("SELECT MAX(received_ts) AS ts FROM chain_events WHERE source = 'webhook'")
        return row["ts"] if row and row["ts"] is not None else None

    # ---------- audit log ----------

    def audit(self, actor: str, action: str, case_id: str | None, detail: Any = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_log (ts, actor, action, case_id, detail_json) VALUES (?,?,?,?,?)",
                (iso(), actor, action, case_id, dumps(detail)),
            )

    def audit_entries(self, case_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if case_id:
            return self._all(
                "SELECT * FROM audit_log WHERE case_id = ? ORDER BY id DESC LIMIT ?", (case_id, limit)
            )
        return self._all("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))

    # ---------- metrics, treasury, poller ----------

    def active_cases(self) -> list[dict[str, Any]]:
        """Non-archived cases (metrics since the last reset)."""
        return self._all(
            "SELECT case_id, counterparty, direction, source, verdict, status, amount_usd, latency_ms,"
            " attestation_status, created_at FROM cases WHERE archived = 0 ORDER BY case_id"
        )

    def queued_attestations(self, max_age_s: float = 86400) -> list[str]:
        """Cases whose attestation never left the queue (e.g. the gate restarted)."""
        rows = self._all(
            "SELECT case_id FROM cases WHERE attestation_status = 'queued' AND archived = 0"
            " AND created_ts >= ? ORDER BY case_id",
            (time.time() - max_age_s,),
        )
        return [r["case_id"] for r in rows]

    def pending_tx_hashes(self, max_age_s: float = 3600) -> list[str]:
        """Attestation txs submitted but not yet confirmed (fallback poller)."""
        rows = self._all(
            "SELECT attestation_tx FROM cases WHERE attestation_status IN ('submitted', 'failed')"
            " AND attestation_tx IS NOT NULL AND created_ts >= ?",
            (time.time() - max_age_s,),
        )
        return [r["attestation_tx"] for r in rows]

    # ---------- demo reset ----------

    def demo_reset(self) -> tuple[int, int]:
        """Archive every case, delete all officer overrides and the idempotency cache.
        Never touches chain events, reports or the Intercepta cache."""
        with self._tx() as c:
            archived = c.execute("UPDATE cases SET archived = 1 WHERE archived = 0").rowcount
            overrides = c.execute("DELETE FROM officer_overrides").rowcount
            c.execute("DELETE FROM idempotency")
            c.execute(
                "INSERT INTO audit_log (ts, actor, action, case_id, detail_json) VALUES (?,?,?,?,?)",
                (iso(), "gate", "demo_reset", None, dumps({"archived": archived, "overrides_cleared": overrides})),
            )
        return archived, overrides
