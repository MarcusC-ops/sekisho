"""Attestation worker and officer decisions against a fake MultiBaas: single nonce lane
per signer, status transitions, argument encoding, reverts -> 409."""

from __future__ import annotations

import asyncio

import pytest
from gate_testkit import MIXER, SANCTIONED, FakeMBError, load_fixture, score_outcome, screen_body, settle

from sekisho_gate.models import ScreenRequest
from sekisho_gate.util import note_hash


def mixer_profile(fakes) -> None:
    fakes.intercepta.quick[MIXER.lower()] = score_outcome("intercepta.quick_scan", load_fixture("mixer_quick_scan.json"))


def sanctioned_profile(fakes) -> None:
    fakes.intercepta.quick[SANCTIONED.lower()] = score_outcome(
        "intercepta.quick_scan", load_fixture("sanctioned_quick_scan.json"))


async def test_not_configured_fails_cleanly(make_services, fakes):
    svc = make_services()  # no MultiBaas client at all
    await svc.start()
    try:
        d = await svc.pipeline.screen(ScreenRequest(**screen_body()))
        assert d["attestation"]["status"] == "queued"
        await settle(svc)
        att = svc.notifier.decision(d["case_id"])["attestation"]
        assert att["status"] == "failed" and "MultiBaas not configured" in att["error"]
        assert att["tx_hash"] is None
    finally:
        await svc.stop()


async def test_status_transitions_and_args(make_services, fakes):
    sanctioned_profile(fakes)
    svc = make_services(with_mb=True)
    q = svc.broker.subscribe()
    await svc.start()
    try:
        d = await svc.pipeline.screen(ScreenRequest(**screen_body(SANCTIONED)))
        await settle(svc)
        seen = []
        while not q.empty():
            msg = q.get_nowait()
            if msg.event in ("case.created", "case.updated"):
                import json

                seen.append(json.loads(msg.data)["attestation"]["status"])
        assert seen[0] == "queued" and "submitted" in seen and seen[-1] == "confirmed"
        assert seen.index("submitted") < seen.index("confirmed")
        w = fakes.mb.writes[0]
        assert (w["alias"], w["label"], w["method"]) == ("compliance_registry", "compliance_registry", "recordScreening")
        assert w["from"] == fakes.screener.address
        assert w["args"] == [SANCTIONED, 3, "100", "31536000", d["report_hash"], svc.policy.id, d["case_id_b32"]]
        att = svc.notifier.decision(d["case_id"])["attestation"]
        assert att["tx_hash"] == w["tx"] and att["explorer_url"] == f"https://sepolia.basescan.org/tx/{w['tx']}"
    finally:
        await svc.stop()


def test_args_match_the_multibaas_encoder():
    """Our pre-encoded args pass through chain.multibaas.encode_args unchanged."""
    mb = pytest.importorskip("sekisho_gate.chain.multibaas")
    args = [SANCTIONED, 3, "100", "31536000", "0x" + "ab" * 32, "0x" + "cd" * 32, "0x" + "ef" * 32]
    assert mb.encode_args(mb.METHOD_TYPES["recordScreening"], args) == args
    ov = [MIXER, 1, "3600", note_hash("ok"), "0x" + "ef" * 32]
    assert mb.encode_args(mb.METHOD_TYPES["overrideVerdict"], ov) == ov
    assert mb.encode_args(mb.METHOD_TYPES["release"], ["3"]) == ["3"]


@pytest.mark.parametrize(
    "setup,error",
    [
        (lambda mb: mb.receipt_status.__setitem__("recordScreening", 0), "reverted onchain"),
        (lambda mb: mb.reverts.__setitem__("recordScreening", FakeMBError("compose failed", revert="InvalidTtl")),
         "recordScreening refused: InvalidTtl"),
        (lambda mb: mb.reverts.__setitem__("recordScreening", FakeMBError("HTTP 503", status=503)), "HTTP 503"),
    ],
    ids=["mined_revert", "compose_revert", "http_error"],
)
async def test_attestation_failures(make_services, fakes, setup, error):
    setup(fakes.mb)
    svc = make_services(with_mb=True)
    await svc.start()
    try:
        d = await svc.pipeline.screen(ScreenRequest(**screen_body()))
        await settle(svc)
        att = svc.notifier.decision(d["case_id"])["attestation"]
        assert att["status"] == "failed" and error in att["error"]
    finally:
        await svc.stop()


async def test_single_nonce_lane_per_signer(make_services, fakes):
    fakes.mb.receipt_delay = 0.03
    svc = make_services(with_mb=True)
    await svc.start()
    try:
        await asyncio.gather(*(
            svc.pipeline.screen(ScreenRequest(**screen_body(amount=str(50000 + i)))) for i in range(6)
        ))
        await settle(svc)
        assert len([w for w in fakes.mb.writes if w["method"] == "recordScreening"]) == 6
        assert fakes.mb.max_open[fakes.screener.address] == 1
        assert all(r["attestation_status"] == "confirmed" for r in svc.store.active_cases())
    finally:
        await svc.stop()


# ---------- officer decisions ----------


async def held_case(g, fakes, *, direction: str = "outbound") -> str:
    mixer_profile(fakes)
    r = await g.client.post("/v1/screen", json=screen_body(MIXER, direction=direction))
    d = r.json()
    assert d["verdict"] == "HOLD"
    if direction == "outbound":
        from unittest.mock import AsyncMock, patch
        from pydantic import SecretStr
        g.svc.settings.buyer_agent_pk = SecretStr(fakes.screener.key.hex())
        # Officer workflow tests isolate receipt verification; receipt/API suites
        # exercise proof checks and rejection before state mutation.
        with patch("sekisho_gate.main.verify_hold_receipt", AsyncMock(return_value={})):
            r = await g.client.post(f"/v1/cases/{d['case_id']}/hold", json={"hold_id": 7, "deposit_tx": "0x" + "d" * 64})
        assert r.json() == {"case_id": d["case_id"], "status": "HELD_ESCROWED"}
    await settle(g.svc)
    return d["case_id"]


async def test_release_outbound(gate, fakes):
    g = await gate(with_mb=True)
    cid = await held_case(g, fakes)
    r = await g.client.post(f"/v1/cases/{cid}/decision", json={"action": "release", "note": "Reviewed, OK"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "RELEASED" and body["override_tx"] and body["action_tx"]
    officer = [w for w in fakes.mb.writes if w["from"] == fakes.officer.address]
    assert [w["method"] for w in officer] == ["overrideVerdict", "release"]
    case = g.svc.store.get_case(cid)
    assert officer[0]["args"] == [MIXER, 1, "3600", note_hash("Reviewed, OK"), case["case_id_b32"]]
    assert officer[1]["args"] == ["7"] and officer[1]["alias"] == "compliance_escrow"
    assert fakes.mb.max_open[fakes.officer.address] == 1
    detail = (await g.client.get(f"/v1/cases/{cid}")).json()
    assert detail["status"] == "RELEASED"
    assert detail["hold"] == {"hold_id": 7, "status": "RELEASED", "deposit_tx": "0x" + "d" * 64,
                              "override_tx": body["override_tx"], "action_tx": body["action_tx"],
                              "officer_note": "Reviewed, OK"}
    # Rule 0: the counterparty is now cleared for the next screening.
    again = (await g.client.post("/v1/screen", json=screen_body(MIXER, amount="70000"))).json()
    assert again["verdict"] == "ALLOW" and "officer_override" in again["policy"]["triggered_rules"]
    await settle(g.svc)
    attest = [w for w in fakes.mb.writes if w["method"] == "recordScreening"][-1]
    assert attest["args"][1] == 1 and 3500 < int(attest["args"][3]) <= 3600  # never outlives the clearance


async def test_refund_outbound_blocks_next_time(gate, fakes):
    g = await gate(with_mb=True)
    cid = await held_case(g, fakes)
    r = await g.client.post(f"/v1/cases/{cid}/decision", json={"action": "refund", "note": "Mixer funds"})
    assert r.status_code == 200 and r.json()["status"] == "REFUNDED"
    officer = [w for w in fakes.mb.writes if w["from"] == fakes.officer.address]
    assert [w["method"] for w in officer] == ["overrideVerdict", "refund"]
    assert officer[0]["args"][1:3] == [3, "31536000"]
    again = (await g.client.post("/v1/screen", json=screen_body(MIXER, amount="70000"))).json()
    assert again["verdict"] == "BLOCK" and again["reasons"][0]["rule"] == "officer_override"


@pytest.mark.parametrize("action,status,verdict", [("release", "CLEARED", 1), ("refund", "REJECTED", 3)])
async def test_inbound_override_only(gate, fakes, action, status, verdict):
    g = await gate(with_mb=True)
    cid = await held_case(g, fakes, direction="inbound")
    r = await g.client.post(f"/v1/cases/{cid}/decision", json={"action": action, "note": "n"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == status and r.json()["action_tx"] is None
    officer = [w for w in fakes.mb.writes if w["from"] == fakes.officer.address]
    assert [w["method"] for w in officer] == ["overrideVerdict"] and officer[0]["args"][1] == verdict
    assert (await g.client.get(f"/v1/cases/{cid}")).json()["hold"] is None


async def test_release_unchecked_revert_is_409(gate, fakes):
    g = await gate(with_mb=True)
    cid = await held_case(g, fakes)
    fakes.mb.reverts["release"] = FakeMBError(
        "compose release: HTTP 400: reverted with NotCleared", body='{"message":"execution reverted 0x92a032ca"}')
    r = await g.client.post(f"/v1/cases/{cid}/decision", json={"action": "release_unchecked", "note": ""})
    assert r.status_code == 409
    assert r.json()["error"] == "NotCleared" and "release(holdId=7)" in r.json()["message"]
    assert g.svc.store.get_case(cid)["status"] == "HELD_ESCROWED"


async def test_revert_decoded_from_selector_only(gate, fakes):
    g = await gate(with_mb=True)
    cid = await held_case(g, fakes)
    fakes.mb.reverts["overrideVerdict"] = FakeMBError("HTTP 400", body='{"message":"reverted: 0xe2517d3f000000"}')
    r = await g.client.post(f"/v1/cases/{cid}/decision", json={"action": "release", "note": "x"})
    assert r.status_code == 409 and r.json()["error"] == "AccessControlUnauthorizedAccount"


async def test_release_unchecked_needs_demo_mode(gate, fakes, make_settings):
    g = await gate(with_mb=True, settings=make_settings(demo_mode=False))
    cid = await held_case(g, fakes)
    r = await g.client.post(f"/v1/cases/{cid}/decision", json={"action": "release_unchecked", "note": ""})
    assert r.status_code == 403 and r.json()["error"] == "demo_mode_only"


async def test_decision_state_checks(gate, fakes):
    g = await gate(with_mb=True)
    allow = (await g.client.post("/v1/screen", json=screen_body())).json()
    r = await g.client.post(f"/v1/cases/{allow['case_id']}/decision", json={"action": "release", "note": ""})
    assert r.status_code == 409 and r.json()["error"] == "invalid_state"
    mixer_profile(fakes)
    hold = (await g.client.post("/v1/screen", json=screen_body(MIXER))).json()
    r = await g.client.post(f"/v1/cases/{hold['case_id']}/decision", json={"action": "release", "note": ""})
    assert r.status_code == 409 and "HELD_ESCROWED" in r.json()["message"]  # no deposit yet
    r = await g.client.post("/v1/cases/cs_NOPE/decision", json={"action": "release", "note": ""})
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    r = await g.client.post(f"/v1/cases/{hold['case_id']}/decision", json={"action": "approve", "note": ""})
    assert r.status_code == 422 and r.json()["error"] == "invalid_request"


async def test_decision_without_multibaas_is_502(gate, fakes):
    g = await gate(with_mb=True)
    cid = await held_case(g, fakes)
    g.svc.attestor.mb = None  # MultiBaas becomes unavailable after the verified deposit
    r = await g.client.post(f"/v1/cases/{cid}/decision", json={"action": "release", "note": ""})
    assert r.status_code == 502 and r.json()["error"] == "chain_error"
