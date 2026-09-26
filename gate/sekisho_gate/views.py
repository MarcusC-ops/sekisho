"""Assemble API objects (docs/api.md) from store rows, and publish case updates."""

from __future__ import annotations

import math
from typing import Any, Callable

from pydantic import ValidationError

from .logs import get_logger
from .models import CaseDetail, ChainEvent, Metrics, ScreeningDecision
from .sse import Broker
from .store import Store, loads
from .util import explorer_tx_url

log = get_logger("sekisho.views")


def attestation_view(row: dict[str, Any], explorer_url: str) -> dict[str, Any]:
    tx = row.get("attestation_tx")
    return {
        "status": row.get("attestation_status") or "queued",
        "tx_hash": tx,
        "explorer_url": explorer_tx_url(explorer_url, tx),
        "error": row.get("attestation_error"),
    }


def hold_view(row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("hold_id") is None:
        return None
    return {
        "hold_id": int(row["hold_id"]),
        "status": row.get("hold_status") or "HELD",
        "deposit_tx": row.get("deposit_tx"),
        "override_tx": row.get("override_tx"),
        "action_tx": row.get("action_tx"),
        "officer_note": row.get("officer_note"),
    }


def _validated(model: Any, data: dict[str, Any]) -> dict[str, Any]:
    try:
        return model.model_validate(data).model_dump(mode="json")
    except ValidationError as exc:  # never break the API over a shape drift; log it loudly
        log.error(
            "response failed %s validation", model.__name__, extra={"errors": exc.errors()[:5]}
        )
        return data


def decision_view(row: dict[str, Any], explorer_url: str, *, validate: bool = True) -> dict[str, Any]:
    """ScreeningDecision: the decision as made, plus the current mutable state."""
    d = loads(row["decision_json"])
    # Legacy stored decisions retain their recorded chain; never guess a signing chain.
    d["payment_chain_id"] = int(row.get("payment_chain_id") or 0)
    deep = loads(row.get("deep_scan_json"))
    if deep and deep.get("check"):
        d["checks"] = [c for c in d["checks"] if c.get("name") != deep["check"]["name"]] + [deep["check"]]
    d["attestation"] = attestation_view(row, explorer_url)
    d["analyst"] = loads(row.get("analyst_json"))
    d["hold"] = hold_view(row)
    d["status"] = row["status"]
    return _validated(ScreeningDecision, d) if validate else d


def chain_event_view(row: dict[str, Any], explorer_url: str) -> dict[str, Any]:
    inputs = row.get("inputs")
    if inputs is None:
        inputs = loads(row.get("inputs_json")) or {}
    return {
        "event_uid": row["event_uid"],
        "name": row["name"],
        "contract_alias": row.get("contract_alias"),
        "tx_hash": row.get("tx_hash"),
        "block_number": row.get("block_number"),
        "log_index": row.get("log_index"),
        "inputs": inputs,
        "case_id": row.get("case_id"),
        "explorer_url": explorer_tx_url(explorer_url, row.get("tx_hash")),
        "received_at": row["received_at"],
    }


def case_detail_view(
    row: dict[str, Any], events: list[dict[str, Any]], explorer_url: str, *, validate: bool = True
) -> dict[str, Any]:
    d = decision_view(row, explorer_url, validate=False)
    evidence = loads(row.get("evidence_json")) or {}
    deep = loads(row.get("deep_scan_json"))
    evidence["deep_scan"] = deep.get("data") if deep else None
    d.update(
        {
            "source": row.get("source") or "direct",
            "agent_id": row.get("agent_id") or "",
            "purpose": row.get("purpose") or "",
            "resource": row.get("resource") or "",
            "payment_chain_id": int(row.get("payment_chain_id") or 0),
            "untrusted_context": row.get("untrusted_context"),
            "payment_tx": row.get("payment_tx"),
            "evidence": {
                k: evidence.get(k) for k in ("quick_scan", "oracle", "impersonation", "token_scan", "deep_scan")
            },
            "chain_events": [chain_event_view(e, explorer_url) for e in events],
        }
    )
    return _validated(CaseDetail, d) if validate else d


def percentile(values: list[int], pct: float) -> int | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return int(ordered[rank - 1])


def metrics_view(rows: list[dict[str, Any]], quota: dict[str, Any] | None) -> dict[str, Any]:
    """PRD 9.12, over non-archived cases (since the last demo reset)."""
    by = {"ALLOW": 0, "HOLD": 0, "BLOCK": 0}
    value = {"ALLOW": 0.0, "HOLD": 0.0, "BLOCK": 0.0}
    latencies, confirmed = [], 0
    for r in rows:
        v = r["verdict"]
        by[v] = by.get(v, 0) + 1
        value[v] = value.get(v, 0.0) + float(r.get("amount_usd") or 0.0)
        if r.get("latency_ms") is not None:
            latencies.append(int(r["latency_ms"]))
        if r.get("attestation_status") == "confirmed":
            confirmed += 1
    m = {
        "window": "since_reset",
        "screened": len(rows),
        "allow": by["ALLOW"],
        "hold": by["HOLD"],
        "block": by["BLOCK"],
        "value_screened_usd": round(sum(value.values()), 6),
        "value_held_usd": round(value["HOLD"], 6),
        "value_blocked_usd": round(value["BLOCK"], 6),
        "latency_ms_p50": percentile(latencies, 50),
        "latency_ms_p95": percentile(latencies, 95),
        "intercepta_calls_used": (quota or {}).get("used"),
        "intercepta_quota": (quota or {}).get("quota"),
        "attestations_confirmed": confirmed,
    }
    return Metrics.model_validate(m).model_dump(mode="json")


class CaseNotifier:
    """Publishes `case.updated` (and `metrics.updated`) after any case change."""

    def __init__(
        self,
        store: Store,
        broker: Broker,
        explorer_url: str,
        quota_fn: Callable[[], dict[str, Any] | None],
    ):
        self.store = store
        self.broker = broker
        self.explorer_url = explorer_url
        self.quota_fn = quota_fn

    def decision(self, case_id: str) -> dict[str, Any] | None:
        row = self.store.get_case(case_id)
        return decision_view(row, self.explorer_url) if row else None

    def metrics(self) -> dict[str, Any]:
        try:
            quota = self.quota_fn()
        except Exception:  # quota is informational
            quota = None
        return metrics_view(self.store.active_cases(), quota)

    def case_created(self, view: dict[str, Any]) -> None:
        self.broker.publish("case.created", view)
        self.broker.publish("metrics.updated", self.metrics())

    def case_updated(self, case_id: str, *, metrics: bool = False) -> dict[str, Any] | None:
        view = self.decision(case_id)
        if view is not None:
            self.broker.publish("case.updated", view)
        if metrics:
            self.broker.publish("metrics.updated", self.metrics())
        return view

    def chain_event(self, event_view: dict[str, Any]) -> None:
        # Validate so SSE consumers get the documented ChainEvent shape.
        self.broker.publish("chain.event", _validated(ChainEvent, event_view))
