"""The HTTP contract (docs/api.md) through httpx.ASGITransport with fake clients."""

from __future__ import annotations

import pytest
from eth_utils import keccak
from gate_testkit import CLEAN, MIXER, SANCTIONED, load_fixture, score_outcome, screen_body, settle

from sekisho_gate.models import CaseDetail, Metrics, ScreeningDecision

DECISION_KEYS = {
    "case_id", "case_id_b32", "verdict", "risk_score", "headline", "direction", "counterparty", "amount",
    "amount_usd", "asset", "reasons", "checks", "trace", "policy", "report_hash", "attestation", "analyst",
    "hold", "status", "decided_at", "latency_ms", "payment_chain_id",
}
DETAIL_EXTRA = {"source", "agent_id", "purpose", "resource", "payment_chain_id", "untrusted_context",
                "payment_tx", "evidence", "chain_events"}


def profiles(fakes) -> None:
    fakes.intercepta.quick[MIXER.lower()] = score_outcome("intercepta.quick_scan", load_fixture("mixer_quick_scan.json"))
    fakes.intercepta.quick[SANCTIONED.lower()] = score_outcome(
        "intercepta.quick_scan", load_fixture("sanctioned_quick_scan.json"))
    fakes.intercepta.quick[CLEAN.lower()] = score_outcome("intercepta.quick_scan", load_fixture("clean_quick_scan.json"))


async def test_screen_returns_the_contract_shape(gate, fakes):
    profiles(fakes)
    g = await gate()
    r = await g.client.post("/v1/screen", json=screen_body(SANCTIONED.lower()))
    assert r.status_code == 200
    d = r.json()
    assert set(d) == DECISION_KEYS
    ScreeningDecision.model_validate(d)
    assert d["case_id"].startswith("cs_") and len(d["case_id"]) == 29
    assert d["case_id_b32"] == "0x" + keccak(text=d["case_id"]).hex()
    assert d["counterparty"] == SANCTIONED  # checksummed
    assert d["verdict"] == "BLOCK" and d["status"] == "REFUSED" and d["risk_score"] == 100
    assert d["amount"] == "50000" and d["amount_usd"] == 0.05
    assert d["attestation"] == {"status": "queued", "tx_hash": None, "explorer_url": None, "error": None}
    assert d["analyst"] is None and d["hold"] is None
    assert d["decided_at"].endswith("Z") and isinstance(d["latency_ms"], int)
    assert d["policy"]["id"] == "0xd55f2a7678cc2571a18073afd351f2fc13ffe4aa9c570632b94a8190f9c14719"
    assert d["reasons"][0]["rule"] == "sanctions_oracle" and "risk" not in d["reasons"][0]
    assert d["reasons"][1]["rule"] == "hard_block_trait:sanction_address" and d["reasons"][1]["risk"] == 100
    assert {c["name"] for c in d["checks"]} >= {"intercepta.quick_scan", "sanctions.oracle", "trace.source_of_funds"}
    qs = d["checks"][0]
    assert set(qs) == {"name", "status", "live", "latency_ms", "summary", "evidence_id", "error"}
    assert d["checks"][1]["live"] is None  # the oracle is not an Intercepta call


@pytest.mark.parametrize(
    "patch,field",
    [
        ({"counterparty": "0x1234"}, "counterparty"),
        ({"counterparty": "0x098b716b8aaf21512996dc57eb0615e2383E2f96"}, "counterparty"),  # bad checksum
        ({"amount": "0.05"}, "amount"),
        ({"amount": -1}, "amount"),
        ({"direction": "sideways"}, "direction"),
        ({"source": "email"}, "source"),
        ({"asset": "USDC"}, "asset"),
    ],
)
async def test_invalid_input_is_422(gate, patch, field):
    g = await gate()
    r = await g.client.post("/v1/screen", json=screen_body(**patch))
    assert r.status_code == 422
    body = r.json()
    assert set(body) == {"error", "message"} and body["error"] == "invalid_request"
    assert body["message"].startswith(field)


async def test_cases_list_and_detail(gate, fakes):
    profiles(fakes)
    g = await gate()
    ids = []
    for who in (CLEAN, MIXER, SANCTIONED):
        ids.append((await g.client.post("/v1/screen", json=screen_body(who))).json()["case_id"])
    await settle(g.svc)
    r = (await g.client.get("/v1/cases")).json()
    assert [i["case_id"] for i in r["items"]] == ids[::-1] and r["next_cursor"] is None
    assert all(set(i) == DECISION_KEYS for i in r["items"])
    assert [i["verdict"] for i in r["items"]] == ["BLOCK", "HOLD", "ALLOW"]
    page = (await g.client.get("/v1/cases", params={"limit": 2})).json()
    assert len(page["items"]) == 2 and page["next_cursor"] == ids[1]
    rest = (await g.client.get("/v1/cases", params={"limit": 2, "cursor": page["next_cursor"]})).json()
    assert [i["case_id"] for i in rest["items"]] == [ids[0]] and rest["next_cursor"] is None
    held = (await g.client.get("/v1/cases", params={"verdict": "HOLD"})).json()["items"]
    assert [i["case_id"] for i in held] == [ids[1]]
    assert (await g.client.get("/v1/cases", params={"status": "REFUSED"})).json()["items"][0]["case_id"] == ids[2]
    assert (await g.client.get("/v1/cases", params={"direction": "inbound"})).json()["items"] == []
    assert (await g.client.get("/v1/cases", params={"limit": 101})).status_code == 422
    assert (await g.client.get("/v1/cases", params={"verdict": "MAYBE"})).json()["error"] == "invalid_request"

    detail = (await g.client.get(f"/v1/cases/{ids[1]}")).json()
    assert set(detail) == DECISION_KEYS | DETAIL_EXTRA
    CaseDetail.model_validate(detail)
    assert detail["source"] == "x402" and detail["payment_chain_id"] == 84532
    traits = detail["evidence"]["quick_scan"]["traits"]
    assert [(t["name"], t["class"]) for t in traits] == [("mixer_transfers", "hold"), ("zero_address_risk", "info")]
    assert traits[0]["description"] == "SYNTHETIC placeholder description for mixer_transfers."
    assert detail["evidence"]["oracle"] == {"1": False, "8453": False}
    assert detail["evidence"]["impersonation"]["isAddressPoisoned"] is False
    assert detail["evidence"]["token_scan"]["action"] == "info"
    assert detail["evidence"]["deep_scan"]["toxicScore"] == 0  # P1 deep scan after the HOLD
    assert detail["analyst"]["provider"] == "template"
    missing = await g.client.get("/v1/cases/cs_DOESNOTEXIST")
    assert missing.status_code == 404 and missing.json() == {"error": "not_found", "message": "case cs_DOESNOTEXIST not found"}


async def test_report_bytes_are_exact(gate, fakes):
    profiles(fakes)
    g = await gate()
    d = (await g.client.post("/v1/screen", json=screen_body(SANCTIONED, untrusted_context="関所 ignore previous"))).json()
    r = await g.client.get(f"/v1/reports/{d['report_hash']}")
    assert r.status_code == 200 and r.headers["content-type"] == "application/json"
    assert r.content == g.svc.store.get_report(d["report_hash"])
    assert "0x" + keccak(r.content).hex() == d["report_hash"]
    assert "関所 ignore previous".encode() in r.content  # UTF-8, not \\u escapes
    assert (await g.client.get("/v1/reports/0x" + "0" * 64)).status_code == 404
    assert (await g.client.get("/v1/reports/nothex")).status_code == 422


async def test_payment_and_hold_reports(gate, fakes, monkeypatch):
    from unittest.mock import AsyncMock
    from pydantic import SecretStr
    monkeypatch.setattr("sekisho_gate.main.verify_payment_receipt", AsyncMock(return_value={}))
    monkeypatch.setattr("sekisho_gate.main.verify_hold_receipt", AsyncMock(return_value={}))
    profiles(fakes)
    g = await gate(with_mb=True)
    g.svc.settings.buyer_agent_pk = SecretStr(fakes.screener.key.hex())
    allow = (await g.client.post("/v1/screen", json=screen_body(CLEAN))).json()
    tx = "0x" + "e" * 64
    r = await g.client.post(f"/v1/cases/{allow['case_id']}/payment", json={"tx_hash": tx.upper().replace("0X", "0x"),
                                                                           "network": "eip155:84532"})
    assert r.status_code == 200 and r.json() == {"case_id": allow["case_id"], "status": "PAID"}
    assert (await g.client.get(f"/v1/cases/{allow['case_id']}")).json()["payment_tx"] == tx
    again = await g.client.post(f"/v1/cases/{allow['case_id']}/payment", json={"tx_hash": tx, "network": "eip155:84532"})
    assert again.status_code == 200  # idempotent
    other = await g.client.post(f"/v1/cases/{allow['case_id']}/payment", json={"tx_hash": "0x" + "f" * 64})
    assert other.status_code == 409 and other.json()["error"] == "invalid_state"
    hold = (await g.client.post("/v1/screen", json=screen_body(MIXER))).json()
    bad = await g.client.post(f"/v1/cases/{hold['case_id']}/payment", json={"tx_hash": tx})
    assert bad.status_code == 409
    r = await g.client.post(f"/v1/cases/{hold['case_id']}/hold", json={"hold_id": 3, "deposit_tx": tx})
    assert r.json() == {"case_id": hold["case_id"], "status": "HELD_ESCROWED"}
    h = (await g.client.get(f"/v1/cases/{hold['case_id']}")).json()["hold"]
    assert h == {"hold_id": 3, "status": "HELD", "deposit_tx": tx, "override_tx": None, "action_tx": None,
                 "officer_note": None}
    conflict = await g.client.post(f"/v1/cases/{hold['case_id']}/hold", json={"hold_id": 4, "deposit_tx": tx})
    assert conflict.status_code == 409
    no_escrow = await g.client.post(f"/v1/cases/{allow['case_id']}/hold", json={"hold_id": 5, "deposit_tx": tx})
    assert no_escrow.status_code == 409


async def test_metrics_and_demo_reset(gate, fakes):
    profiles(fakes)
    g = await gate()
    for who in (CLEAN, MIXER, SANCTIONED):
        await g.client.post("/v1/screen", json=screen_body(who))
    g.svc.store.put_override(MIXER, "ALLOW", 4_102_444_800, None, None)
    m = (await g.client.get("/v1/metrics")).json()
    Metrics.model_validate(m)
    assert (m["window"], m["screened"], m["allow"], m["hold"], m["block"]) == ("since_reset", 3, 1, 1, 1)
    assert m["value_screened_usd"] == pytest.approx(0.15) and m["value_blocked_usd"] == pytest.approx(0.05)
    assert m["intercepta_quota"] == 1000 and m["latency_ms_p50"] is not None
    r = await g.client.post("/v1/demo/reset")
    assert r.json() == {"archived": 3, "overrides_cleared": 1}
    assert (await g.client.get("/v1/cases")).json()["items"] == []
    assert (await g.client.get("/v1/metrics")).json()["screened"] == 0
    assert g.svc.store.active_override(MIXER) is None
    # Idempotency cache cleared: the same request makes a new case.
    again = (await g.client.post("/v1/screen", json=screen_body(CLEAN))).json()
    assert (await g.client.get(f"/v1/cases/{again['case_id']}")).status_code == 200
    assert len((await g.client.get("/v1/cases")).json()["items"]) == 1


async def test_demo_reset_needs_demo_mode(gate, make_settings):
    g = await gate(settings=make_settings(demo_mode=False))
    r = await g.client.post("/v1/demo/reset")
    assert r.status_code == 403 and r.json()["error"] == "demo_mode_only"


async def test_healthz_policy_quota_treasury(gate):
    g = await gate()
    h = await g.client.get("/healthz")
    assert h.status_code == 200
    body = h.json()
    assert body["status"] == "degraded"  # no MultiBaas, unreachable RPC in tests
    assert set(body["checks"]) == {"intercepta", "oracle_self_test", "multibaas", "contracts_rpc", "llm"}
    assert body["checks"]["multibaas"]["ok"] is False and body["policy"]["version"] == "1.0.0"
    p = (await g.client.get("/v1/policy")).json()
    assert p["id"] == body["policy"]["id"] and p["name"] == "sekisho-demo-policy"
    assert p["yaml"].startswith("# Sekisho demo policy") and p["parsed"]["thresholds"]["block_score"] == 80
    q = (await g.client.get("/v1/quota")).json()
    assert set(q) == {"used", "quota", "remaining", "warn_at", "reserve_from"}
    t = await g.client.get("/v1/treasury")
    assert t.status_code == 200
    tb = t.json()
    assert tb["escrow_total_held"] is None and tb["exposure_by_payee"] is None and tb["errors"]
    assert tb["source"] == "multibaas" and tb["counterparty_book"] == []


async def test_treasury_with_multibaas(gate, fakes):
    from gate_testkit import FakeMBError

    fakes.mb.reads[("compliance_escrow", "totalHeld")] = "500000"
    fakes.mb.queries["exposure_by_payee"] = [{"payee": MIXER.lower(), "total": 500000}]
    fakes.mb.queries["released_by_payee"] = FakeMBError("query failed", status=502)
    profiles(fakes)
    g = await gate(with_mb=True)
    await g.client.post("/v1/screen", json=screen_body(SANCTIONED, amount="25050000"))
    t = (await g.client.get("/v1/treasury")).json()
    assert t["escrow_total_held"] == "500000" and t["escrow_total_held_usd"] == 0.5
    assert t["exposure_by_payee"] == [{"payee": MIXER, "total": "500000", "total_usd": 0.5}]
    assert t["released_by_payee"] is None and any("released_by_payee" in e for e in t["errors"])
    assert t["value_blocked_usd"] == 25.05
    assert t["counterparty_book"][0]["latest_verdict"] == "BLOCK"


async def test_cors_allows_console_origin(gate):
    g = await gate()
    r = await g.client.options(
        "/v1/cases", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    r = await g.client.get("/v1/metrics", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


async def test_unknown_route_uses_error_shape(gate):
    g = await gate()
    r = await g.client.get("/v1/nope")
    assert r.status_code == 404 and r.json()["error"] == "not_found"


@pytest.mark.parametrize("path,body", [
    ("/v1/demo/reset", {}),
    ("/v1/cases/cs_NONEXISTENT/decision", {"action": "release", "note": "reviewed"}),
])
@pytest.mark.parametrize("authorization", ["", "Bearer wrong", "Basic test-operator-token", "Bearer tést"])
async def test_operator_actions_reject_invalid_credentials(gate, path, body, authorization):
    g = await gate()
    response = await g.client.post(path, json=body, headers={"Authorization": authorization.encode()})
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized", "message": "A valid operator token is required."}
    assert g.svc.store.list_cases()[0] == []


@pytest.mark.parametrize("path,body", [
    ("/v1/demo/reset", {}),
    ("/v1/cases/cs_NONEXISTENT/decision", {"action": "release", "note": "reviewed"}),
])
async def test_operator_actions_disabled_without_configuration(gate, make_settings, path, body):
    g = await gate(settings=make_settings(sekisho_operator_token=""))
    response = await g.client.post(path, json=body)
    assert response.status_code == 503
    assert response.json()["error"] == "operator_unconfigured"
    assert (await g.client.get("/v1/cases")).status_code == 200


async def test_unauthenticated_reset_preserves_cases_and_overrides(gate, fakes):
    profiles(fakes)
    g = await gate()
    await g.client.post("/v1/screen", json=screen_body(CLEAN))
    g.svc.store.put_override(MIXER, "ALLOW", 4_102_444_800, None, None)
    g.client.headers.pop("Authorization")
    assert (await g.client.post("/v1/demo/reset")).status_code == 401
    assert len((await g.client.get("/v1/cases")).json()["items"]) == 1
    assert g.svc.store.active_override(MIXER) is not None


@pytest.mark.parametrize("patch", [
    {"payment_chain_id": 1},
    {"payment_chain_id": 8453},
    {"asset": "0x" + "1" * 40},
])
async def test_screen_rejects_unsupported_payment_asset(gate, patch):
    g = await gate()
    response = await g.client.post("/v1/screen", json=screen_body(**patch))
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"
    assert (await g.client.get("/v1/cases")).json()["items"] == []


async def test_unverified_reports_do_not_change_case(gate, fakes, monkeypatch):
    from unittest.mock import AsyncMock
    from pydantic import SecretStr
    from sekisho_gate.receipts import ReceiptValidationError
    profiles(fakes)
    g = await gate(with_mb=True)
    g.svc.settings.buyer_agent_pk = SecretStr(fakes.screener.key.hex())
    for counterparty, endpoint, body in [
        (CLEAN, "payment", {"tx_hash": "0x" + "a" * 64}),
        (MIXER, "hold", {"hold_id": 7, "deposit_tx": "0x" + "b" * 64}),
    ]:
        failure = AsyncMock(side_effect=ReceiptValidationError("No matching verified event"))
        monkeypatch.setattr(f"sekisho_gate.main.verify_{endpoint}_receipt", failure)
        case = (await g.client.post("/v1/screen", json=screen_body(counterparty))).json()
        result = await g.client.post(f"/v1/cases/{case['case_id']}/{endpoint}", json=body)
        assert result.status_code == 409
        assert g.svc.store.get_case(case["case_id"])["status"] == "DECIDED"
        assert failure.await_args.kwargs["payer"] == fakes.screener.address
        assert failure.await_args.kwargs["payee"] == counterparty
        assert failure.await_args.kwargs["min_timestamp"] > 0


async def test_payment_reports_require_buyer_and_outbound_network(gate, fakes):
    g = await gate()
    for changes, network, status in [({}, "eip155:84532", 503),
                                      ({}, "eip155:1", 409),
                                      ({"direction": "inbound"}, "eip155:84532", 409)]:
        case = (await g.client.post("/v1/screen", json=screen_body(CLEAN, **changes))).json()
        result = await g.client.post(f"/v1/cases/{case['case_id']}/payment",
                                     json={"tx_hash": "0x" + "a" * 64, "network": network})
        assert result.status_code == status
        assert g.svc.store.get_case(case["case_id"])["status"] == "DECIDED"


async def test_payment_receipt_cannot_be_reused_after_archive(gate, fakes, monkeypatch):
    from unittest.mock import AsyncMock
    from pydantic import SecretStr
    monkeypatch.setattr("sekisho_gate.main.verify_payment_receipt", AsyncMock(return_value={}))
    g = await gate()
    g.svc.settings.buyer_agent_pk = SecretStr(fakes.screener.key.hex())
    tx = "0x" + "a" * 64
    first = (await g.client.post("/v1/screen", json=screen_body(CLEAN))).json()
    assert (await g.client.post(f"/v1/cases/{first['case_id']}/payment", json={"tx_hash": tx})).status_code == 200
    g.svc.store.demo_reset()
    second = (await g.client.post("/v1/screen", json=screen_body(CLEAN))).json()
    result = await g.client.post(f"/v1/cases/{second['case_id']}/payment", json={"tx_hash": tx})
    assert result.status_code == 409
    assert g.svc.store.get_case(second["case_id"])["status"] == "DECIDED"


async def test_rpc_wait_cannot_overwrite_later_hold_state(gate, fakes, monkeypatch):
    from pydantic import SecretStr
    profiles(fakes)
    g = await gate(with_mb=True)
    g.svc.settings.buyer_agent_pk = SecretStr(fakes.screener.key.hex())
    case = (await g.client.post("/v1/screen", json=screen_body(MIXER))).json()

    async def released_while_waiting(*args, **kwargs):
        g.svc.store.update_case(case["case_id"], status="RELEASED", hold_id=7, hold_status="RELEASED")
        return {}

    monkeypatch.setattr("sekisho_gate.main.verify_hold_receipt", released_while_waiting)
    result = await g.client.post(f"/v1/cases/{case['case_id']}/hold",
                                 json={"hold_id": 7, "deposit_tx": "0x" + "d" * 64})
    assert result.json()["status"] == "RELEASED"
    assert g.svc.store.get_case(case["case_id"])["hold_status"] == "RELEASED"


async def test_atomic_payment_acceptance_revalidates_state(gate, fakes, monkeypatch):
    from pydantic import SecretStr
    g = await gate()
    g.svc.settings.buyer_agent_pk = SecretStr(fakes.screener.key.hex())
    case = (await g.client.post("/v1/screen", json=screen_body(CLEAN))).json()

    async def rejected_while_waiting(*args, **kwargs):
        g.svc.store.update_case(case["case_id"], status="REJECTED")
        return {}

    monkeypatch.setattr("sekisho_gate.main.verify_payment_receipt", rejected_while_waiting)
    result = await g.client.post(f"/v1/cases/{case['case_id']}/payment", json={"tx_hash": "0x" + "a" * 64})
    assert result.status_code == 409
    assert g.svc.store.get_case(case["case_id"])["status"] == "REJECTED"


async def test_two_cases_cannot_claim_one_payment_concurrently(gate):
    import asyncio
    from sekisho_gate.errors import GateError
    g = await gate()
    cases = [(await g.client.post("/v1/screen", json=screen_body(CLEAN, resource=str(i)))).json()
             for i in range(2)]

    def accept(case_id):
        try:
            return g.svc.store.record_verified_payment(case_id, "0x" + "a" * 64, "eip155:84532")
        except GateError as exc:
            return exc.status

    outcomes = await asyncio.gather(*(asyncio.to_thread(accept, c["case_id"]) for c in cases))
    assert sorted(outcomes, key=str) == [409, True]
    assert sum(g.svc.store.get_case(c["case_id"])["status"] == "PAID" for c in cases) == 1
