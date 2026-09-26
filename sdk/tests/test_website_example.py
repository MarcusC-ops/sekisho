"""Exercise the exact example distributed on the public website."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest
import respx

spec = importlib.util.spec_from_file_location(
    "screen_example", Path(__file__).parents[1] / "examples/screen_before_signing.py"
)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)
GATE = "http://gate.test"
WALLET = "0x" + "12" * 20


@pytest.mark.parametrize("verdict", ["ALLOW", "HOLD", "BLOCK"])
async def test_example_preserves_gate_verdict_and_usdc_units(make_decision, verdict):
    with respx.mock() as router:
        route = router.post(f"{GATE}/v1/screen").respond(200, json=make_decision(verdict))
        assert await example.screen_payment(WALLET, GATE) == verdict
    body = json.loads(route.calls.last.request.content)
    assert (body["amount"], body["asset"], body["payment_chain_id"]) == (
        "50000", "0x036CbD53842c5426634e7929541eC2318f3dCF7e", 84532
    )
    assert body["counterparty"] == WALLET


@pytest.mark.parametrize("response", [
    {"side_effect": httpx.ReadTimeout("timed out")},
    {"return_value": httpx.Response(503)},
    {"return_value": httpx.Response(422, json={"error": "invalid_request"})},
    {"return_value": httpx.Response(200, json={"verdict": "ALLOW"})},
])
async def test_example_never_allows_without_a_complete_decision(response):
    with respx.mock() as router:
        router.post(f"{GATE}/v1/screen").mock(**response)
        assert await example.screen_payment(WALLET, GATE) == "HOLD"
