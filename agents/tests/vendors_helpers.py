"""Helpers shared by test_vendors.py and test_rogue.py.

agents/ is not a package and pytest runs with --import-mode=importlib, so the tests load this
file, the vendor app and the rogue payer by path. All HTTP is mocked with respx (AGENTS.md
rule 4). The vendor app is driven in-process through httpx.ASGITransport, which respx does
not intercept.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
import respx

HERE = Path(__file__).resolve().parent
AGENTS = HERE.parent

GATE = "http://gate.test"
FACILITATOR = "https://facilitator.test"
VENDOR = "http://vendor.test"
NET = "eip155:84532"
USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
PAY_TO = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"  # EIP-55 test vector, stands in for VENDOR_CLEAN_PAYTO
ROGUE = "0xa0e1c89Ef1a489c9C7dE96311eD5Ce5D32c20E4B"  # ROGUE_PAYER_ADDR (PRD 7.3)
CLEAN_PAYER = "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359"  # EIP-55 test vector, a buyer that passes
CASE = "cs_01J8Z6Q4M0T3R9ABCDEFGHJKMN"
SETTLE_TX = "0x" + "ab" * 32
SUPPORTED = json.loads((HERE / "vendors_supported.json").read_text())  # real x402.org /supported

HEADLINES = {"ALLOW": "No risk found", "HOLD": "Counterparty has mixer exposure",
             "BLOCK": "Counterparty is on a sanctions list"}


def load(relpath: str, name: str) -> ModuleType:
    """Import a file under agents/ by path (cached in sys.modules, which dataclasses need)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, AGENTS / relpath)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def decision(verdict: str, counterparty: str, *, direction: str = "inbound", case_id: str = CASE,
             amount: str = "50000") -> dict[str, Any]:
    """A ScreeningDecision body shaped like docs/api.md."""
    reasons = [] if verdict == "ALLOW" else [
        {"rule": "hard_block_trait:sanction_address", "severity": "block", "source": "intercepta",
         "label": "sanction_address", "detail": "Intercepta description, verbatim", "evidence_id": "E1",
         "risk": 100, "txs_count": 0},
        {"rule": "sanctions_oracle", "severity": "block", "source": "chainalysis",
         "label": "Sanctioned address (onchain oracle)", "detail": "isSanctioned = true on Ethereum",
         "evidence_id": "E2"},
    ]
    return {
        "case_id": case_id, "case_id_b32": "0x" + "5c1e" * 16, "verdict": verdict,
        "risk_score": {"ALLOW": 2, "HOLD": 55, "BLOCK": 100}[verdict], "headline": HEADLINES[verdict],
        "direction": direction, "counterparty": counterparty, "amount": amount,
        "amount_usd": int(amount) / 1_000_000, "asset": USDC, "payment_chain_id": 84532, "reasons": reasons,
        "checks": [{"name": "intercepta.quick_scan", "status": "ok", "live": True, "latency_ms": 312,
                    "summary": "toxicScore 100, 3 traits", "evidence_id": "E1"}],
        "trace": None,
        "policy": {"id": "0x" + "9f" * 32, "version": "1.0.0", "triggered_rules": [r["rule"] for r in reasons]},
        "report_hash": "0x" + "41" * 32, "attestation": {"status": "queued", "tx_hash": None, "explorer_url": None},
        "analyst": None, "hold": None, "status": "REFUSED" if verdict == "BLOCK" else "DECIDED",
        "decided_at": "2026-09-26T10:21:33Z", "latency_ms": 2210,
    }


def mock_facilitator(router: respx.MockRouter) -> SimpleNamespace:
    """/supported (fetched synchronously when the middleware starts), /verify and /settle."""
    def verify(request: httpx.Request) -> httpx.Response:
        payer = json.loads(request.content)["paymentPayload"]["payload"]["authorization"]["from"]
        return httpx.Response(200, json={"isValid": True, "payer": payer})

    def settle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        payer = body["paymentPayload"]["payload"]["authorization"]["from"]
        return httpx.Response(200, json={"success": True, "transaction": SETTLE_TX, "network": NET,
                                         "payer": payer, "amount": body["paymentRequirements"]["amount"]})

    return SimpleNamespace(
        supported=router.get(f"{FACILITATOR}/supported").mock(return_value=httpx.Response(200, json=SUPPORTED)),
        verify=router.post(f"{FACILITATOR}/verify").mock(side_effect=verify),
        settle=router.post(f"{FACILITATOR}/settle").mock(side_effect=settle),
    )


def mock_gate(router: respx.MockRouter, verdicts: dict[str, str] | None = None, **mock: Any) -> respx.Route:
    """POST /v1/screen. `verdicts` maps counterparty -> verdict; or pass respx mock kwargs."""
    route = router.post(f"{GATE}/v1/screen")
    if mock:
        return route.mock(**mock)

    def answer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        verdict = (verdicts or {}).get(body["counterparty"], "ALLOW")
        return httpx.Response(200, json=decision(verdict, body["counterparty"], direction=body["direction"],
                                                 amount=body["amount"]))

    return route.mock(side_effect=answer)


def asgi_client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=VENDOR)
