"""MultiBaas webhook receiver: HMAC accept/reject, idempotent replay, case updates per
event (PRD 9.13), SSE fan-out, and the fallback poller."""

from __future__ import annotations

import json
import time

import pytest
from gate_testkit import MIXER, load_fixture, mb_event, score_outcome, screen_body, settle, sign_webhook, webhook_functions

TX1 = "0x" + "a1" * 32
TX2 = "0x" + "b2" * 32
TX3 = "0x" + "c3" * 32


async def post_webhook(client, items, *, secret_ok: bool = True, ts: str | None = None, sig: str | None = None):
    body = json.dumps(items).encode()
    ts = ts if ts is not None else str(int(time.time()))
    sig = sig if sig is not None else sign_webhook(body, ts) if secret_ok else "00" * 32
    return await client.post(
        "/webhooks/multibaas", content=body,
        headers={"X-MultiBaas-Timestamp": ts, "X-MultiBaas-Signature": sig, "Content-Type": "application/json"},
    )


def test_uses_the_integration_verifier():
    _, _, source = webhook_functions()
    assert source == "chain.multibaas"


async def test_hmac_accept_and_reject(gate):
    g = await gate()
    ok = await post_webhook(g.client, [])
    assert ok.status_code == 200 and ok.json() == {"ok": True}
    bad = await post_webhook(g.client, [], secret_ok=False)
    assert bad.status_code == 401 and bad.json()["error"] == "unauthorized"
    body = b"[]"
    missing = await g.client.post("/webhooks/multibaas", content=body)
    assert missing.status_code == 401
    ts = str(int(time.time()))
    tampered = await g.client.post(
        "/webhooks/multibaas", content=b'[{"event":"event.emitted"}]',
        headers={"X-MultiBaas-Timestamp": ts, "X-MultiBaas-Signature": sign_webhook(body, ts)},
    )
    assert tampered.status_code == 401


async def test_no_secret_rejects_everything(gate, make_settings):
    g = await gate(settings=make_settings(mb_webhook_secret=""))
    r = await post_webhook(g.client, [])
    assert r.status_code == 401


async def screened_case(g, fakes):
    fakes.intercepta.quick[MIXER.lower()] = score_outcome("intercepta.quick_scan", load_fixture("mixer_quick_scan.json"))
    d = (await g.client.post("/v1/screen", json=screen_body(MIXER))).json()
    await settle(g.svc)
    return d


async def test_screened_confirms_and_replay_is_idempotent(gate, fakes):
    g = await gate()
    d = await screened_case(g, fakes)
    assert g.svc.store.get_case(d["case_id"])["attestation_status"] == "failed"  # no MultiBaas configured
    q = g.svc.broker.subscribe()
    inputs = {"subject": MIXER.lower(), "verdict": "2", "riskScore": "60", "reportHash": d["report_hash"],
              "policyId": d["policy"]["id"], "expiresAt": "1790000000", "screener": "0x" + "5" * 40,
              "caseId": d["case_id_b32"]}
    item = mb_event("Screened", inputs, tx_hash=TX1, log_index=3)
    for _ in range(2):  # MultiBaas retries deliveries: the second must change nothing
        r = await post_webhook(g.client, [item])
        assert r.status_code == 200
    events = g.svc.store.list_chain_events()
    assert len(events) == 1 and events[0]["event_uid"] == f"{TX1}:3"
    detail = (await g.client.get(f"/v1/cases/{d['case_id']}")).json()
    assert detail["attestation"]["status"] == "confirmed" and detail["attestation"]["tx_hash"] == TX1
    ev = detail["chain_events"][0]
    assert ev["name"] == "Screened" and ev["case_id"] == d["case_id"] and ev["log_index"] == 3
    assert ev["inputs"]["verdict"] == 2 and ev["inputs"]["riskScore"] == 60 and ev["inputs"]["expiresAt"] == 1790000000
    assert ev["inputs"]["subject"] == MIXER and ev["inputs"]["reportHash"] == d["report_hash"]
    assert ev["explorer_url"] == f"https://sepolia.basescan.org/tx/{TX1}"
    names = []
    while not q.empty():
        names.append(q.get_nowait().event)
    assert names.count("chain.event") == 1 and "case.updated" in names
    audit = (await g.client.get("/v1/audit", params={"case_id": d["case_id"]})).json()["items"]
    assert [e["name"] for e in audit] == ["Screened"]


async def test_held_released_refunded_and_override(gate, fakes):
    g = await gate()
    d = await screened_case(g, fakes)
    b32 = d["case_id_b32"]
    held = mb_event("Held", {"holdId": "4", "caseId": b32, "payer": "0x" + "6" * 40, "payee": MIXER, "amount": "50000"},
                    tx_hash=TX1, alias="compliance_escrow")
    assert (await post_webhook(g.client, [held])).status_code == 200
    case = (await g.client.get(f"/v1/cases/{d['case_id']}")).json()
    assert case["status"] == "HELD_ESCROWED"
    assert case["hold"] == {"hold_id": 4, "status": "HELD", "deposit_tx": TX1, "override_tx": None,
                            "action_tx": None, "officer_note": None}
    override = mb_event("VerdictOverridden", {"subject": MIXER, "previous": "2", "next": "1",
                                              "noteHash": "0x" + "7" * 64, "officer": "0x" + "8" * 40,
                                              "caseId": b32}, tx_hash=TX2)
    released = mb_event("Released", {"holdId": "4", "caseId": b32, "payee": MIXER, "amount": "50000",
                                     "officer": "0x" + "8" * 40}, tx_hash=TX3, alias="compliance_escrow")
    assert (await post_webhook(g.client, [override, released])).status_code == 200
    case = (await g.client.get(f"/v1/cases/{d['case_id']}")).json()
    assert case["status"] == "RELEASED"
    assert case["hold"]["status"] == "RELEASED" and case["hold"]["action_tx"] == TX3 and case["hold"]["override_tx"] == TX2
    assert [e["name"] for e in case["chain_events"]] == ["Held", "VerdictOverridden", "Released"]
    audit = g.svc.store.audit_entries(case_id=d["case_id"])
    assert any(a["action"] == "VerdictOverridden" for a in audit)
    # A late, replayed Held never moves a released case backwards.
    assert (await post_webhook(g.client, [held])).status_code == 200
    assert g.svc.store.get_case(d["case_id"])["status"] == "RELEASED"


async def test_refunded_event(gate, fakes):
    g = await gate()
    d = await screened_case(g, fakes)
    b32 = d["case_id_b32"]
    items = [
        mb_event("Held", {"holdId": "9", "caseId": b32, "payer": "0x" + "6" * 40, "payee": MIXER, "amount": "1"},
                 tx_hash=TX1),
        mb_event("Refunded", {"holdId": "9", "caseId": b32, "payer": "0x" + "6" * 40, "amount": "1",
                              "by": "0x" + "8" * 40}, tx_hash=TX2),
    ]
    await post_webhook(g.client, items)
    row = g.svc.store.get_case(d["case_id"])
    assert (row["status"], row["hold_status"], row["hold_id"]) == ("REFUNDED", "REFUNDED", 9)


async def test_unknown_case_and_other_items_are_stored_or_skipped(gate):
    g = await gate()
    item = mb_event("Screened", {"caseId": "0x" + "9" * 64, "verdict": "1"}, tx_hash=TX1)
    other = {"id": "x", "event": "transaction.included", "data": {}}
    r = await post_webhook(g.client, [item, other])
    assert r.status_code == 200
    events = g.svc.store.list_chain_events()
    assert len(events) == 1 and events[0]["case_id"] is None


async def test_fallback_poller_fetches_by_tx_hash(make_services, fakes):
    from sekisho_gate.models import ScreenRequest

    svc = make_services(with_mb=True)
    await svc.start()
    try:
        d = await svc.pipeline.screen(ScreenRequest(**screen_body()))
        await settle(svc)
        tx = svc.store.get_case(d["case_id"])["attestation_tx"]
        from sekisho_gate.chain.multibaas import parse_event

        fakes.mb.events_by_tx[tx] = [parse_event(mb_event("Screened", {"caseId": d["case_id_b32"], "verdict": "1"},
                                                          tx_hash=tx, log_index=1)["data"])]
        assert await svc.poller.poll_once() == 0  # too early: webhooks get 60 s first
        found = await svc.poller.poll_once(now=time.time() + 61)
        assert found == 1
        ev = svc.store.list_chain_events()[0]
        assert ev["source"] == "poller" and ev["case_id"] == d["case_id"]
        assert tx not in svc.poller.tracked or await svc.poller.poll_once(now=time.time() + 61) == 0
    finally:
        await svc.stop()


@pytest.mark.parametrize("value,expected", [("12", 12), (12, 12), (str(2**60), str(2**60)), ("0x10", 16)])
def test_integer_inputs(value, expected):
    from sekisho_gate.webhooks import normalise_inputs

    assert normalise_inputs({"amount": value})["amount"] == expected
