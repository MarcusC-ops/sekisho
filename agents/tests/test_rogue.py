"""S5 simulated spoofed payer (PRD 10.4): payload shape, and the vendor refusing it end to end."""

from __future__ import annotations

import base64
import importlib.util
import json
import re
from pathlib import Path

import httpx
import pytest
import respx
from x402.http.utils import decode_payment_signature_header
from x402.schemas import PaymentPayload

from sekisho import SekishoClient
from sekisho.x402_hooks import payer_address


def _load_helpers():
    import sys

    if "vendors_helpers" not in sys.modules:
        spec = importlib.util.spec_from_file_location("vendors_helpers", Path(__file__).with_name("vendors_helpers.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules["vendors_helpers"] = module
        spec.loader.exec_module(module)
    return sys.modules["vendors_helpers"]


H = _load_helpers()
vendor_app = H.load("vendors/app.py", "sekisho_vendor_app")
spoof = H.load("rogue/spoofed_payer.py", "sekisho_spoofed_payer")

ACCEPTS0 = {"scheme": "exact", "network": H.NET, "asset": H.USDC, "amount": "50000", "payTo": H.PAY_TO,
            "maxTimeoutSeconds": 300, "extra": {"name": "USDC", "version": "2"}}
REQUIRED = {"x402Version": 2, "error": "Payment required", "accepts": [ACCEPTS0],
            "resource": {"url": f"{H.VENDOR}/v1/market-data", "description": "d", "mimeType": "application/json"}}


def test_spoofed_payment_is_a_v2_payload_from_the_rogue_address():
    payment = spoof.build_spoofed_payment(REQUIRED, H.ROGUE, now=1_790_000_000)
    assert payment["x402Version"] == 2
    assert payment["accepted"] == ACCEPTS0  # verbatim, or the vendor never gets to screening
    auth = payment["payload"]["authorization"]
    assert auth == {"from": H.ROGUE, "to": H.PAY_TO, "value": "50000", "validAfter": "0",
                    "validBefore": str(1_790_000_000 + 300), "nonce": auth["nonce"]}
    assert re.fullmatch(r"0x[0-9a-f]{64}", auth["nonce"])
    assert re.fullmatch(r"0x[0-9a-f]{130}", payment["payload"]["signature"])  # 65 random bytes
    assert payment["resource"] == REQUIRED["resource"]

    header = spoof.encode_payment_header(payment)
    base64.b64decode(header, validate=True)  # standard base64, as x402 encodes it
    decoded = decode_payment_signature_header(header)  # what the vendor middleware does
    assert isinstance(decoded, PaymentPayload)
    assert payer_address(decoded) == H.ROGUE
    assert decoded.accepted.pay_to == H.PAY_TO and decoded.accepted.amount == "50000"


def test_each_spoof_has_a_fresh_signature_and_nonce():
    a, b = (spoof.build_spoofed_payment(REQUIRED, H.ROGUE)["payload"] for _ in range(2))
    assert a["signature"] != b["signature"] and a["authorization"]["nonce"] != b["authorization"]["nonce"]


def test_a_402_without_accepts_is_a_run_error():
    with pytest.raises(spoof.SpoofRunError):
        spoof.build_spoofed_payment({"x402Version": 2, "accepts": []}, H.ROGUE)


# ---------------------------------------------------------------------------- end to end


@pytest.fixture
async def sk():
    client = SekishoClient(H.GATE, timeout_s=1.0)
    yield client
    await client.aclose()


@pytest.fixture
def router():
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as r:
        yield r


def vendor(sk, **overrides):
    cfg = vendor_app.VendorConfig(**{
        "vendor_id": "vendor-clean", "name": "Kabuto Market Data", "pay_to": H.PAY_TO,
        "sekisho_url": H.GATE, "facilitator_url": H.FACILITATOR, "network": H.NET, **overrides})
    return H.asgi_client(vendor_app.create_app(cfg, sekisho=sk))


async def test_vendor_refuses_the_spoofed_payer_at_the_payer_gate(router, sk, capsys):
    fac = H.mock_facilitator(router)
    gate = H.mock_gate(router, {H.ROGUE: "BLOCK"})
    async with vendor(sk) as http:
        result = await spoof.run(H.VENDOR, H.ROGUE, http=http)
    assert (result.accepted, result.refused_by, result.verdict, result.case_id) == (
        False, "payer_gate", "BLOCK", H.CASE)
    assert result.screened and result.exit_code == 0 and result.status_code == 403
    assert "sanction_address" in result.reasons
    assert gate.call_count == 1 and json.loads(gate.calls.last.request.content)["counterparty"] == H.ROGUE
    assert not fac.verify.called and not fac.settle.called
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines and all(line.startswith("[Simulated spoofed payer] ") for line in lines)
    assert any("REFUSED: HTTP 403 payer_refused. Sekisho verdict BLOCK" in line for line in lines)


async def test_vendor_refuses_the_spoofed_payer_in_before_verify(router, sk):
    fac = H.mock_facilitator(router)
    H.mock_gate(router, {H.ROGUE: "BLOCK"})
    async with vendor(sk, payer_gate=False) as http:
        result = await spoof.run(H.VENDOR, H.ROGUE, http=http, say=lambda _: None)
    assert (result.refused_by, result.verdict, result.case_id, result.status_code) == (
        "payee_hook", "BLOCK", H.CASE, 402)
    assert result.reasons == ["Counterparty is on a sanctions list"] and result.exit_code == 0
    assert not fac.verify.called and not fac.settle.called


async def test_exit_code_is_1_if_the_vendor_accepts(router, sk, capsys):
    H.mock_facilitator(router)  # verify says valid, settle succeeds
    H.mock_gate(router)  # and the gate lets everyone through
    async with vendor(sk) as http:
        result = await spoof.run(H.VENDOR, H.ROGUE, http=http)
    assert result.accepted and result.exit_code == 1
    assert "ACCEPTED" in capsys.readouterr().out


async def test_a_refusal_that_is_not_screening_is_flagged(router, sk, capsys):
    router.get(f"{H.FACILITATOR}/supported").mock(return_value=httpx.Response(200, json=H.SUPPORTED))
    router.post(f"{H.FACILITATOR}/verify").mock(return_value=httpx.Response(200, json={
        "isValid": False, "invalidReason": "invalid_exact_evm_payload_signature", "payer": H.ROGUE}))
    H.mock_gate(router)  # ALLOW: screening let it through, the facilitator caught the random signature
    async with vendor(sk) as http:
        result = await spoof.run(H.VENDOR, H.ROGUE, http=http)
    assert (result.accepted, result.refused_by, result.exit_code) == (False, "x402", 0)
    assert not result.screened and result.detail == "invalid_exact_evm_payload_signature"
    assert "WARNING" in capsys.readouterr().out


def test_main_exits_2_when_the_vendor_is_unreachable(router, capsys):
    router.get(f"{H.VENDOR}/v1/market-data").mock(side_effect=httpx.ConnectError("refused"))
    assert spoof.main(["--vendor", H.VENDOR, "--payer", H.ROGUE, "--json"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["label"] == "Simulated spoofed payer" and "unreachable" in out["error"]


def test_classify_other_statuses():
    assert spoof.classify(httpx.Response(500, text="boom")).refused_by == "vendor"
    assert spoof.classify(httpx.Response(200, json={})).accepted
