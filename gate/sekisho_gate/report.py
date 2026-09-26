"""The hashed evidence report (PRD 9.7).

The report holds the deterministic parts only: the request, every check with its raw
upstream response, the trace, the triggered rules, the verdict, the risk score, the
policy id and version, and timestamps. The AI analyst note and the post-HOLD Deep Scan
are NOT in it (they are advisory and arrive later).

Canonical bytes are exactly
    json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
and report_hash = "0x" + keccak(bytes).hex(). The gate stores and serves those exact
bytes; the browser hashes the served text (Appendix F).
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Any, Iterable

from eth_utils import keccak

from .checks import CHECK_ORDER, EVIDENCE_IDS
from .screening.types import CheckOutcome

SCHEMA = "sekisho.report.v1"


def canonical_bytes(report: dict[str, Any]) -> bytes:
    return json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def report_hash(data: bytes) -> str:
    return "0x" + keccak(data).hex()


def sanitize(value: Any) -> Any:
    """Make a value safe for canonical JSON: NaN/inf -> None, tuples -> lists, keys -> str,
    datetimes -> ISO strings. Applied BEFORE hashing, so stored bytes and hash agree."""
    if isinstance(value, dict):
        return {str(k): sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        return [sanitize(v) for v in items]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def check_entry(outcome: CheckOutcome) -> dict[str, Any]:
    return {
        "name": outcome.name,
        "evidence_id": EVIDENCE_IDS.get(outcome.name),
        "status": outcome.status,
        "live": outcome.live,
        "latency_ms": outcome.latency_ms,
        "summary": outcome.summary,
        "error": outcome.error,
        "data": outcome.data,
        "raw": outcome.raw,
    }


def ordered_checks(outcomes: Iterable[CheckOutcome]) -> list[CheckOutcome]:
    rank = {name: i for i, name in enumerate(CHECK_ORDER)}
    return sorted(outcomes, key=lambda o: rank.get(o.name, len(rank)))


def build_report(
    *,
    case_id: str,
    case_id_b32: str,
    request: dict[str, Any],
    amount_usd: float,
    received_at: str,
    decided_at: str,
    checks: Iterable[CheckOutcome],
    trace: dict[str, Any] | None,
    policy: dict[str, str],
    decision: Any,
    history: dict[str, Any],
    fault_inject: str | None = None,
) -> dict[str, Any]:
    """`decision` is a policy.PolicyDecision; `policy` is {"id", "version", "name"}."""
    report = {
        "schema": SCHEMA,
        "case_id": case_id,
        "case_id_b32": case_id_b32,
        "request": {**request, "amount_usd": amount_usd},
        "received_at": received_at,
        "decided_at": decided_at,
        "checks": [check_entry(o) for o in ordered_checks(checks)],
        "trace": trace,
        "policy": {
            "id": policy["id"],
            "version": policy["version"],
            "name": policy["name"],
            "triggered_rules": list(decision.triggered_rules),
        },
        "officer_override": decision.override,
        "history": history,
        "verdict": decision.verdict,
        "risk_score": decision.risk_score,
        "headline": decision.headline,
        "reasons": decision.reasons,
    }
    if fault_inject:
        report["fault_inject"] = fault_inject
    return sanitize(report)


def seal(report: dict[str, Any]) -> tuple[bytes, str]:
    """Canonical bytes and their hash."""
    data = canonical_bytes(report)
    return data, report_hash(data)
