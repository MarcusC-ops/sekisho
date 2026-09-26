"""Shared fixtures for the SDK tests. All HTTP is mocked with respx (AGENTS.md rule 4)."""

from __future__ import annotations

from typing import Any

import pytest

GATE = "http://gate.test"
USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # Base Sepolia USDC (PRD 7.1)
SANCTIONED = "0x098B716B8Aaf21512996dC57EB0615e2383E2f96"  # PRD 7.3, S3
CASE_ID = "cs_01J8Z6Q4M0T3R9ABCDEFGHJKMN"

HEADLINES = {
    "ALLOW": "No risk found",
    "HOLD": "Counterparty has mixer exposure",
    "BLOCK": "Counterparty is on a sanctions list",
}


def decision_json(
    verdict: str = "ALLOW",
    *,
    counterparty: str = SANCTIONED,
    direction: str = "outbound",
    case_id: str = CASE_ID,
    amount: str = "50000",
    **overrides: Any,
) -> dict[str, Any]:
    """A ScreeningDecision body shaped exactly like docs/api.md."""
    reasons = (
        []
        if verdict == "ALLOW"
        else [
            {"rule": "hard_block_trait:sanction_address", "severity": "block", "source": "intercepta",
             "label": "sanction_address", "detail": "Intercepta description, verbatim",
             "evidence_id": "E1", "risk": 100, "txs_count": 0},
            {"rule": "sanctions_oracle", "severity": "block", "source": "chainalysis",
             "label": "Sanctioned address (onchain oracle)", "detail": "isSanctioned = true on Ethereum",
             "evidence_id": "E2"},
        ]
    )
    body: dict[str, Any] = {
        "case_id": case_id,
        "case_id_b32": "0x" + "5c1e" * 16,
        "verdict": verdict,
        "risk_score": {"ALLOW": 3, "HOLD": 55, "BLOCK": 100}.get(verdict, 50),
        "headline": HEADLINES.get(verdict, "?"),
        "direction": direction,
        "counterparty": counterparty,
        "amount": amount,
        "amount_usd": int(amount) / 1_000_000,
        "asset": USDC,
        "payment_chain_id": 84532,
        "reasons": reasons,
        "checks": [
            {"name": "intercepta.quick_scan", "status": "ok", "live": True, "latency_ms": 312,
             "summary": "toxicScore 100, 3 traits", "evidence_id": "E1", "error": None},
            {"name": "sanctions.oracle", "status": "ok", "latency_ms": 188,
             "summary": "sanctioned on 1", "evidence_id": "E2"},
        ],
        "trace": None,
        "policy": {"id": "0x" + "9f" * 32, "version": "1.0.0",
                   "triggered_rules": [r["rule"] for r in reasons]},
        "report_hash": "0x" + "41" * 32,
        "attestation": {"status": "queued", "tx_hash": None, "explorer_url": None},
        "analyst": None,
        "hold": None,
        "status": "REFUSED" if verdict == "BLOCK" else "DECIDED",
        "decided_at": "2026-09-26T10:21:33Z",
        "latency_ms": 2210,
    }
    body.update(overrides)
    return body


@pytest.fixture
def make_decision():
    return decision_json
