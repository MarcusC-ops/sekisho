"""MCP server (mcp/server.py, PRD 10.5): tools against a respx-mocked gate, called directly
and through an in-process MCP client."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

import httpx  # noqa: E402
import mcp  # noqa: E402
import pytest  # noqa: E402
import respx  # noqa: E402
from mcp import Client  # noqa: E402


def load_server() -> Any:
    """mcp/server.py by path: the local mcp/ folder is not a package (it must not shadow the SDK)."""
    spec = importlib.util.spec_from_file_location("sekisho_mcp_server", ROOT / "mcp" / "server.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


server = load_server()
SETTINGS = server.get_settings()
GATE = SETTINGS.sekisho_url.rstrip("/")
CONSOLE = SETTINGS.console_origin.rstrip("/")
SANCTIONED = "0x098B716B8Aaf21512996dC57EB0615e2383E2f96"


def decision(verdict: str = "BLOCK", case_id: str = "cs_01J8Z6Q4M0T3R9ABCDEFGHJKMN") -> dict[str, Any]:
    return {
        "case_id": case_id, "case_id_b32": "0x" + "5c" * 32, "verdict": verdict, "risk_score": 100,
        "headline": "Counterparty is on a sanctions list", "direction": "outbound", "counterparty": SANCTIONED,
        "amount": "1500000", "amount_usd": 1.5, "asset": server.BASE_SEPOLIA_USDC,
        "reasons": [
            {"rule": "sanctions_oracle", "severity": "block", "source": "chainalysis",
             "label": "Sanctioned address (onchain oracle)", "detail": "isSanctioned = true on Ethereum",
             "evidence_id": "E2"},
            {"rule": "hard_block_trait:sanction_address", "severity": "block", "source": "intercepta",
             "label": "sanction_address", "detail": "Verbatim Intercepta description", "evidence_id": "E1",
             "risk": 100, "txs_count": 0},
        ],
        "checks": [{"name": "intercepta.quick_scan", "status": "ok", "live": True, "latency_ms": 312,
                    "summary": "toxicScore 100, 3 traits", "evidence_id": "E1"}],
        "trace": None, "policy": {"id": "0x" + "9f" * 32, "version": "1.0.0",
                                  "triggered_rules": ["sanctions_oracle", "hard_block_trait:sanction_address"]},
        "report_hash": "0x" + "41" * 32, "attestation": {"status": "queued", "tx_hash": None, "explorer_url": None},
        "analyst": None, "hold": None, "status": "REFUSED", "decided_at": "2026-09-26T10:21:33Z", "latency_ms": 2210,
    }


def test_the_sdk_is_not_shadowed_by_the_local_mcp_folder():
    assert not (ROOT / "mcp" / "__init__.py").exists()
    assert "site-packages" in (mcp.__file__ or "")


@respx.mock
async def test_screen_counterparty_calls_the_gate_as_an_mcp_agent():
    route = respx.post(f"{GATE}/v1/screen").mock(return_value=httpx.Response(200, json=decision()))
    out = await server.screen_counterparty(SANCTIONED.lower(), "outbound", 1.5, "Pay invoice INV-2291")
    body = json.loads(route.calls.last.request.content)
    assert body["counterparty"] == SANCTIONED and body["direction"] == "outbound"
    assert body["source"] == "mcp" and body["agent_id"] == "mcp-agent"
    assert body["asset"] == "0x036CbD53842c5426634e7929541eC2318f3dCF7e" and body["payment_chain_id"] == 84532
    assert body["amount"] == "1500000" and body["purpose"] == "Pay invoice INV-2291"
    assert out["verdict"] == "BLOCK" and out["risk_score"] == 100
    assert out["headline"] == "Counterparty is on a sanctions list"
    assert out["reasons"][1] == {"label": "sanction_address", "detail": "Verbatim Intercepta description",
                                 "source": "intercepta", "severity": "block"}
    assert out["case_url"] == f"{CONSOLE}/cases/cs_01J8Z6Q4M0T3R9ABCDEFGHJKMN" and out["intercepta_ms"] == 312


@respx.mock
async def test_screen_counterparty_fails_closed_when_the_gate_is_down():
    respx.post(f"{GATE}/v1/screen").mock(side_effect=httpx.ConnectError("connection refused"))
    out = await server.screen_counterparty(SANCTIONED)
    assert out["verdict"] == "HOLD" and out["case_id"] is None and "Unavailable" in out["error"]


@respx.mock
async def test_screen_counterparty_rejects_bad_input_without_calling_the_gate():
    route = respx.post(f"{GATE}/v1/screen")
    with pytest.raises(ValueError):
        await server.screen_counterparty("0x1234")
    with pytest.raises(ValueError):
        await server.screen_counterparty(SANCTIONED, direction="sideways")
    with pytest.raises(ValueError):
        await server.screen_counterparty(SANCTIONED, amount_usd=-1)
    assert not route.called


@respx.mock
async def test_get_case_list_and_policy():
    respx.get(f"{GATE}/v1/cases/cs_X").mock(return_value=httpx.Response(200, json={**decision(case_id="cs_X"),
                                                                                  "untrusted_context": None}))
    respx.get(f"{GATE}/v1/cases").mock(return_value=httpx.Response(200, json={"items": [decision()],
                                                                             "next_cursor": None}))
    respx.get(f"{GATE}/v1/policy").mock(return_value=httpx.Response(200, json={
        "id": "0xd55f", "version": "1.0.0", "name": "sekisho-demo-policy", "yaml": "name: sekisho-demo-policy\n",
        "parsed": {"thresholds": {"block_score": 80, "hold_score": 40, "taint_block_pct": 50,
                                  "taint_hold_pct": 10, "first_time_max_usd": 25},
                   "hard_block_traits": ["sanction_address"], "hold_traits": ["mixer_transfers"],
                   "info_traits": ["fake_phishing_transfer"]}}))
    case = await server.get_case("cs_X")
    assert case["case_id"] == "cs_X" and case["case_url"] == f"{CONSOLE}/cases/cs_X"
    recent = await server.list_recent_decisions(5)
    assert recent[0]["verdict"] == "BLOCK" and recent[0]["case_url"].endswith("/cases/cs_01J8Z6Q4M0T3R9ABCDEFGHJKMN")
    assert respx.calls[1].request.url.params["limit"] == "5"
    policy = await server.explain_policy()
    assert policy["version"] == "1.0.0" and policy["thresholds"]["block_score"] == 80
    assert any("80 or more" in line for line in policy["plain_english"])


@respx.mock
async def test_unknown_case_is_a_tool_error():
    respx.get(f"{GATE}/v1/cases/cs_NOPE").mock(return_value=httpx.Response(404, json={"error": "not_found",
                                                                                     "message": "case cs_NOPE"}))
    with pytest.raises(ValueError, match="cs_NOPE"):
        await server.get_case("cs_NOPE")


@respx.mock
async def test_tools_over_the_mcp_protocol():
    respx.post(f"{GATE}/v1/screen").mock(return_value=httpx.Response(200, json=decision()))
    async with Client(server.mcp) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert names == {"screen_counterparty", "get_case", "list_recent_decisions", "explain_policy"}
        result = await client.call_tool("screen_counterparty", {"address": SANCTIONED, "amount_usd": 0.05})
    assert not result.is_error
    assert result.structured_content["verdict"] == "BLOCK"
