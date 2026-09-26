"""SekishoClient: request shapes, Decision parsing and the fail-closed error mapping."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from sekisho import Decision, SekishoClient, SekishoRequestError, SekishoUnavailable

GATE = "http://gate.test"
USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
SANCTIONED = "0x098B716B8Aaf21512996dC57EB0615e2383E2f96"
CASE = "cs_01J8Z6Q4M0T3R9ABCDEFGHJKMN"

SCREEN_ARGS = dict(
    counterparty=SANCTIONED,
    direction="outbound",
    amount="50000",
    asset=USDC,
    payment_chain_id=84532,
    source="x402",
    agent_id="treasury-agent-01",
    purpose="Buy ETH/JPY market data",
    resource="http://localhost:4023/v1/market-data",
)


@pytest.fixture
async def sk():
    client = SekishoClient(GATE + "/", timeout_s=1.5)
    yield client
    await client.aclose()


async def test_screen_posts_the_contract_body_and_parses_the_decision(sk, make_decision):
    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(f"{GATE}/v1/screen").mock(
            return_value=httpx.Response(200, json=make_decision("BLOCK", case_id=CASE))
        )
        d = await sk.screen(**SCREEN_ARGS)
    assert json.loads(route.calls.last.request.content) == {**SCREEN_ARGS, "untrusted_context": None}
    assert isinstance(d, Decision)
    assert (d.verdict, d.case_id, d.risk_score) == ("BLOCK", CASE, 100)
    assert d.headline == "Counterparty is on a sanctions list"
    assert [r.label for r in d.reasons] == ["sanction_address", "Sanctioned address (onchain oracle)"]
    assert d.reasons[0].risk == 100 and d.reasons[1].risk is None
    assert d.check("intercepta.quick_scan").latency_ms == 312
    assert d.check("intercepta.quick_scan").live is True
    assert d.policy.version == "1.0.0" and d.attestation.status == "queued"
    assert d.allowed is False


async def test_decision_keeps_fields_the_gate_adds_later(sk, make_decision):
    body = make_decision("ALLOW", explorer_hint="new field", policy={
        "id": "0x" + "9f" * 32, "version": "1.1.0", "triggered_rules": [], "jurisdiction": "JP"})
    with respx.mock() as router:
        router.post(f"{GATE}/v1/screen").mock(return_value=httpx.Response(200, json=body))
        d = await sk.screen(**SCREEN_ARGS)
    assert d.allowed
    assert d.model_extra["explorer_hint"] == "new field"
    assert d.policy.model_extra["jurisdiction"] == "JP"


@pytest.mark.parametrize(
    "mock",
    [
        {"side_effect": httpx.ConnectError("connection refused")},
        {"side_effect": httpx.ConnectTimeout("connect timed out")},
        {"side_effect": httpx.ReadTimeout("read timed out")},
        {"side_effect": httpx.RemoteProtocolError("peer closed connection")},
        {"return_value": httpx.Response(500, json={"error": "internal", "message": "boom"})},
        {"return_value": httpx.Response(502, text="Bad Gateway")},
        {"return_value": httpx.Response(503)},
        {"return_value": httpx.Response(200, text="<html>not json</html>")},
        {"return_value": httpx.Response(200, json={"case_id": CASE})},  # not a decision
        {"return_value": httpx.Response(200, json={"items": []})},
    ],
    ids=["connect", "connect-timeout", "read-timeout", "protocol", "500", "502", "503",
         "non-json", "partial", "wrong-shape"],
)
async def test_screen_raises_unavailable_when_the_gate_gives_no_usable_answer(sk, mock):
    with respx.mock() as router:
        router.post(f"{GATE}/v1/screen").mock(**mock)
        with pytest.raises(SekishoUnavailable):
            await sk.screen(**SCREEN_ARGS)


async def test_unknown_verdict_is_unavailable_not_a_guess(sk, make_decision):
    with respx.mock() as router:
        router.post(f"{GATE}/v1/screen").mock(
            return_value=httpx.Response(200, json={**make_decision("ALLOW"), "verdict": "MAYBE"})
        )
        with pytest.raises(SekishoUnavailable, match="invalid decision"):
            await sk.screen(**SCREEN_ARGS)


async def test_5xx_keeps_the_status_code(sk):
    with respx.mock() as router:
        router.post(f"{GATE}/v1/screen").mock(
            return_value=httpx.Response(503, json={"error": "quota_reserved", "message": "Intercepta reserve"})
        )
        with pytest.raises(SekishoUnavailable) as info:
            await sk.screen(**SCREEN_ARGS)
    assert info.value.status_code == 503
    assert "quota_reserved" in str(info.value)


async def test_4xx_is_a_request_error_with_the_gate_error_code(sk):
    with respx.mock() as router:
        router.post(f"{GATE}/v1/screen").mock(
            return_value=httpx.Response(422, json={"error": "invalid_request", "message": "bad address"})
        )
        with pytest.raises(SekishoRequestError) as info:
            await sk.screen(**SCREEN_ARGS)
    assert (info.value.status_code, info.value.error, info.value.message) == (422, "invalid_request", "bad address")
    assert not isinstance(info.value, SekishoUnavailable)


async def test_screen_rejects_bad_enums_without_calling_the_gate(sk):
    with respx.mock(assert_all_called=False) as router:
        route = router.post(f"{GATE}/v1/screen")
        with pytest.raises(ValueError, match="direction"):
            await sk.screen(**{**SCREEN_ARGS, "direction": "sideways"})
        with pytest.raises(ValueError, match="source"):
            await sk.screen(**{**SCREEN_ARGS, "source": "email"})
    assert not route.called


async def test_report_payment_and_hold_post_the_contract_bodies(sk):
    with respx.mock() as router:
        pay = router.post(f"{GATE}/v1/cases/{CASE}/payment").mock(
            return_value=httpx.Response(200, json={"case_id": CASE, "status": "PAID"}))
        hold = router.post(f"{GATE}/v1/cases/{CASE}/hold").mock(
            return_value=httpx.Response(200, json={"case_id": CASE, "status": "HELD_ESCROWED"}))
        assert await sk.report_payment(CASE, "0x" + "ab" * 32, "eip155:84532") is None
        assert await sk.report_hold(CASE, 3, "0x" + "cd" * 32) is None
    assert json.loads(pay.calls.last.request.content) == {"tx_hash": "0x" + "ab" * 32, "network": "eip155:84532"}
    assert json.loads(hold.calls.last.request.content) == {"hold_id": 3, "deposit_tx": "0x" + "cd" * 32}


async def test_report_payment_maps_errors(sk):
    with respx.mock() as router:
        router.post(f"{GATE}/v1/cases/{CASE}/payment").mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(SekishoUnavailable):
            await sk.report_payment(CASE, "0x" + "ab" * 32, "eip155:84532")


async def test_get_case_returns_the_detail_dict_and_404_is_a_request_error(sk, make_decision):
    detail = {**make_decision("BLOCK", case_id=CASE), "payment_tx": None, "chain_events": []}
    with respx.mock() as router:
        router.get(f"{GATE}/v1/cases/{CASE}").mock(return_value=httpx.Response(200, json=detail))
        router.get(f"{GATE}/v1/cases/cs_missing").mock(
            return_value=httpx.Response(404, json={"error": "not_found", "message": "no such case"}))
        assert await sk.get_case(CASE) == detail
        with pytest.raises(SekishoRequestError) as info:
            await sk.get_case("cs_missing")
    assert info.value.error == "not_found"


async def test_list_cases_sends_filters_and_returns_decisions(sk, make_decision):
    with respx.mock() as router:
        route = router.get(f"{GATE}/v1/cases").mock(return_value=httpx.Response(200, json={
            "items": [make_decision("BLOCK", case_id=CASE), make_decision("ALLOW", case_id="cs_2")],
            "next_cursor": None}))
        cases = await sk.list_cases(limit=5, verdict="BLOCK", direction=None)
    assert dict(route.calls.last.request.url.params) == {"limit": "5", "verdict": "BLOCK"}
    assert [(c.case_id, c.verdict) for c in cases] == [(CASE, "BLOCK"), ("cs_2", "ALLOW")]


async def test_policy_returns_the_dict(sk):
    policy = {"id": "0x" + "9f" * 32, "version": "1.0.0", "name": "demo", "yaml": "...", "parsed": {}}
    with respx.mock() as router:
        router.get(f"{GATE}/v1/policy").mock(return_value=httpx.Response(200, json=policy))
        assert await sk.policy() == policy


async def test_async_context_manager_closes_the_http_client():
    async with SekishoClient(GATE) as client:
        assert not client._http.is_closed
    assert client._http.is_closed
