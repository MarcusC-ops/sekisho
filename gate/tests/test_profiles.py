"""The three demo profiles (clean ALLOW, mixer HOLD, sanctioned BLOCK) end to end: the
REAL Intercepta client and sanctions oracle over respx-mocked HTTP, serving the Intercepta
bodies in data/intercepta/*.json (SYNTHETIC until real captures are dropped in; the
assertions read the fixture files, so a swap needs no test edits)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from gate_testkit import CLEAN, MIXER, SANCTIONED, load_fixture, screen_body, settle, trace_outcome

from sekisho_gate.models import ScreenRequest

PROFILES = {
    CLEAN.lower(): "clean_quick_scan.json",
    MIXER.lower(): "mixer_quick_scan.json",
    SANCTIONED.lower(): "sanctioned_quick_scan.json",
}


def rpc_answer(request: httpx.Request) -> httpx.Response:
    """Chainalysis isSanctioned(address) eth_call: true only for the S3 address."""
    payload = json.loads(request.content)
    calls = payload if isinstance(payload, list) else [payload]
    out = []
    for call in calls:
        data = call["params"][0]["data"].lower()
        hit = data.endswith(SANCTIONED.lower()[2:])
        out.append({"jsonrpc": "2.0", "id": call["id"], "result": "0x" + ("0" * 63) + ("1" if hit else "0")})
    return httpx.Response(200, json=out if isinstance(payload, list) else out[0])


def address_from(request: httpx.Request) -> str:
    parts = request.url.path.split("/")
    return next(p for p in parts if p.startswith("0x"))


def score_answer(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=load_fixture(PROFILES[address_from(request)]))


@pytest.fixture
def intercepta_http():
    with respx.mock(assert_all_called=False) as router:
        base = "https://api.web3antivirus.io/api/public"
        router.get(url__regex=rf"^{base}/v2/extension/account/0x[0-9a-f]{{40}}/quick-scan$").mock(side_effect=score_answer)
        router.get(url__regex=rf"^{base}/v2/extension/account/0x[0-9a-f]{{40}}/toxic-score$").mock(side_effect=score_answer)
        router.get(url__regex=rf"^{base}/v1/extension/poisoning-attack/check-address/0x[0-9a-f]{{40}}$").mock(
            return_value=httpx.Response(200, json=load_fixture("impersonation_clean.json")))
        router.get(url__regex=rf"^{base}/v2/extension/token-intelligence/token/0x[0-9a-f]{{40}}/risks").mock(
            return_value=httpx.Response(200, json=load_fixture("token_base_usdc.json")))
        router.post("https://ethereum-rpc.publicnode.com").mock(side_effect=rpc_answer)
        router.post("https://mainnet.base.org").mock(side_effect=rpc_answer)
        yield router


@pytest.fixture
async def real_clients(make_services, make_settings, fakes, intercepta_http):
    from sekisho_gate.screening.intercepta import InterceptaClient
    from sekisho_gate.screening.sanctions import SanctionsOracle

    settings = make_settings()
    fakes.tracer.answers[MIXER.lower()] = trace_outcome(12.5, ["Tornado Cash: Router → counterparty (Ethereum, $1,250)"])
    svc = make_services(settings=settings, intercepta=InterceptaClient(settings), oracle=SanctionsOracle(settings))
    await svc.start()
    yield svc, intercepta_http
    await svc.stop()


def trait_names(name: str) -> list[str]:
    return [t["name"] for t in load_fixture(name)["traits"]]


async def test_clean_profile_allows(real_clients):
    svc, _ = real_clients
    d = await svc.pipeline.screen(ScreenRequest(**screen_body(CLEAN)))
    assert d["verdict"] == "ALLOW" and d["status"] == "DECIDED"
    assert d["reasons"] == [] and d["policy"]["triggered_rules"] == ["default"]
    qs = d["checks"][0]
    assert qs["name"] == "intercepta.quick_scan" and qs["status"] == "ok" and qs["live"] is True
    await settle(svc)
    row = svc.store.get_case(d["case_id"])
    evidence = json.loads(row["evidence_json"])
    body = load_fixture("clean_quick_scan.json")
    assert [t["name"] for t in evidence["quick_scan"]["traits"]] == trait_names("clean_quick_scan.json")
    assert evidence["quick_scan"]["traits"][0]["class"] == "info"  # info trait shown, verdict unchanged
    assert evidence["quick_scan"]["traits"][0]["description"] == body["traits"][0]["description"]
    assert evidence["oracle"] == {"1": False, "8453": False}
    report = json.loads(svc.store.get_report(d["report_hash"]))
    assert report["checks"][0]["raw"] == body  # the raw Intercepta response is in the hashed report


async def test_mixer_profile_holds(real_clients):
    svc, router = real_clients
    d = await svc.pipeline.screen(ScreenRequest(**screen_body(MIXER)))
    assert d["verdict"] == "HOLD"
    rules = d["policy"]["triggered_rules"]
    assert "hold_trait:mixer_transfers" in rules and "taint_hold" in rules
    assert not [r for r in d["reasons"] if r["severity"] == "block"]
    mixer = next(r for r in d["reasons"] if r["rule"] == "hold_trait:mixer_transfers")
    fixture_trait = next(t for t in load_fixture("mixer_quick_scan.json")["traits"] if t["name"] == "mixer_transfers")
    assert mixer["detail"] == fixture_trait["description"]  # verbatim
    assert d["trace"]["taint_pct"] == 12.5
    await settle(svc)
    detail = svc.notifier.decision(d["case_id"])
    deep = next(c for c in detail["checks"] if c["name"] == "intercepta.deep_scan")
    assert deep["status"] == "ok"
    assert svc.intercepta.quota_status()["used"] == 4  # quick + impersonation + token + deep


async def test_sanctioned_profile_blocks(real_clients):
    svc, _ = real_clients
    d = await svc.pipeline.screen(ScreenRequest(**screen_body(SANCTIONED, amount="25000000")))
    assert d["verdict"] == "BLOCK" and d["status"] == "REFUSED" and d["risk_score"] == 100
    assert d["headline"] == "Counterparty is on a sanctions list"
    assert d["reasons"][0]["rule"] == "sanctions_oracle"
    assert d["reasons"][0]["detail"] == "isSanctioned = true on Ethereum and Base"
    assert "hard_block_trait:sanction_address" in d["policy"]["triggered_rules"]
    oracle = next(c for c in d["checks"] if c["name"] == "sanctions.oracle")
    assert oracle["status"] == "ok" and oracle["evidence_id"] == "E2"
