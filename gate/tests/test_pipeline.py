"""Screening pipeline: fail closed, timeouts and the 8 s budget, fault injection, evidence
ids, the token-scan mapping, idempotency and the background work."""

from __future__ import annotations

import asyncio
import json

import pytest
from eth_utils import keccak
from gate_testkit import (
    BASE_USDC,
    CLEAN,
    MIXER,
    SANCTIONED,
    error_outcome,
    load_fixture,
    score_outcome,
    screen_body,
    settle,
)

from sekisho_gate import checks as check_consts
from sekisho_gate.models import ScreenRequest
from sekisho_gate.screening import pipeline as pipeline_mod
from sekisho_gate.screening.types import CheckOutcome


def req(counterparty: str = CLEAN, **kw) -> ScreenRequest:
    return ScreenRequest(**screen_body(counterparty, **kw))


def check(view: dict, name: str) -> dict:
    return next(c for c in view["checks"] if c["name"] == name)


# ---------- fail closed ----------


@pytest.mark.parametrize(
    "quick",
    [
        error_outcome("intercepta.quick_scan", "HTTP 500"),
        RuntimeError("connection reset"),
        CheckOutcome(name="intercepta.quick_scan", status="ok", data={"unexpected": True}),
        CheckOutcome(name="intercepta.quick_scan", status="skipped", summary="skipped"),
        "not a CheckOutcome",
    ],
    ids=["error", "raises", "bad_shape", "skipped", "wrong_type"],
)
async def test_quick_scan_failure_is_at_least_hold(make_services, fakes, quick):
    fakes.intercepta.quick[CLEAN.lower()] = quick
    svc = make_services()
    await svc.start()
    try:
        d = await svc.pipeline.screen(req())
        assert d["verdict"] == "HOLD"
        assert "screening_error" in d["policy"]["triggered_rules"]
        qs = check(d, "intercepta.quick_scan")
        assert qs["status"] in ("error", "skipped") and qs["evidence_id"] == "E1"
        if qs["status"] == "error":
            assert qs["error"]
    finally:
        await svc.stop()


async def test_quick_scan_timeout_holds(make_services, fakes, monkeypatch):
    monkeypatch.setitem(check_consts.TIMEOUTS_S, "intercepta.quick_scan", 0.2)
    fakes.intercepta.quick[CLEAN.lower()] = 5.0  # hangs
    svc = make_services()
    await svc.start()
    try:
        d = await svc.pipeline.screen(req())
        assert d["verdict"] == "HOLD"
        qs = check(d, "intercepta.quick_scan")
        assert qs["status"] == "error" and qs["error"] == "timeout after 200 ms"
        assert d["headline"] == "Screening unavailable, payment held"
    finally:
        await svc.stop()


async def test_quick_scan_failure_is_never_allow_even_with_officer_clearance(make_services, fakes):
    svc = make_services()
    svc.store.put_override(CLEAN, "ALLOW", 4_102_444_800, "cs_PRIOR", None)
    fakes.intercepta.quick[CLEAN.lower()] = error_outcome("intercepta.quick_scan", "HTTP 429")
    await svc.start()
    try:
        d = await svc.pipeline.screen(req())
        assert d["verdict"] == "HOLD"
        assert d["policy"]["triggered_rules"] == ["officer_override", "screening_error"]
    finally:
        await svc.stop()


async def test_fault_injection_times_out_the_quick_scan(make_services, make_settings, fakes, monkeypatch):
    monkeypatch.setitem(check_consts.TIMEOUTS_S, "intercepta.quick_scan", 0.3)
    svc = make_services(settings=make_settings(fault_inject="intercepta_timeout"))
    await svc.start()
    try:
        d = await svc.pipeline.screen(req())
        assert d["verdict"] == "HOLD"
        qs = check(d, "intercepta.quick_scan")
        assert qs["status"] == "error"
        assert "fault injected" in qs["error"] and "intercepta_timeout" in qs["error"]
        assert ("quick_scan", CLEAN) not in fakes.intercepta.calls  # no Intercepta call, no quota
        await settle(svc)
        deep = check(svc.notifier.decision(d["case_id"]), "intercepta.deep_scan")
        assert deep["status"] == "skipped"
    finally:
        await svc.stop()


async def test_overall_budget_fails_closed(make_services, fakes, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "OVERALL_BUDGET_S", 0.3)
    monkeypatch.setitem(check_consts.TIMEOUTS_S, "intercepta.quick_scan", 5.0)
    fakes.intercepta.quick[CLEAN.lower()] = 3.0
    svc = make_services()
    await svc.start()
    try:
        d = await svc.pipeline.screen(req())
        assert d["verdict"] == "HOLD"
        assert "budget exceeded" in check(d, "intercepta.quick_scan")["error"]
        assert d["latency_ms"] < 2000
    finally:
        await svc.stop()


async def test_failed_checks_are_recorded_not_dropped(make_services, fakes):
    fakes.oracle.answers[CLEAN.lower()] = RuntimeError("rpc down")
    fakes.tracer.answers[CLEAN.lower()] = error_outcome("trace.source_of_funds", "no Blockscout data")
    svc = make_services()
    await svc.start()
    try:
        d = await svc.pipeline.screen(req())
        names = [c["name"] for c in d["checks"]]
        assert names == ["intercepta.quick_scan", "sanctions.oracle", "trace.source_of_funds",
                         "intercepta.impersonation", "intercepta.token"]
        assert [c["evidence_id"] for c in d["checks"]] == ["E1", "E2", "E3", "E4", "E5"]
        assert check(d, "sanctions.oracle")["status"] == "error"
        assert "rpc down" in check(d, "sanctions.oracle")["error"]
        assert check(d, "trace.source_of_funds")["status"] == "error"
        assert d["trace"] is None
        report = json.loads(svc.store.get_report(d["report_hash"]))
        assert [c["status"] for c in report["checks"]][1:3] == ["error", "error"]
        assert d["verdict"] == "ALLOW"  # only the Quick Scan is fail-closed (rule 7)
    finally:
        await svc.stop()


# ---------- checks config ----------


async def test_token_scan_targets_mainnet_equivalent(make_services, fakes):
    svc = make_services()
    await svc.start()
    try:
        await svc.pipeline.screen(req())
        assert ("token", f"8453:{BASE_USDC}") in fakes.intercepta.calls
    finally:
        await svc.stop()


async def test_p1_checks_can_be_disabled(make_services, make_settings, fakes):
    svc = make_services(settings=make_settings(screen_token=False, screen_impersonation=False))
    await svc.start()
    try:
        d = await svc.pipeline.screen(req())
        for name in ("intercepta.token", "intercepta.impersonation"):
            c = check(d, name)
            assert c["status"] == "skipped" and c["summary"] == "disabled by config"
        report = json.loads(svc.store.get_report(d["report_hash"]))
        assert {c["name"]: c["status"] for c in report["checks"]}["intercepta.token"] == "skipped"
        assert not [c for c in fakes.intercepta.calls if c[0] in ("token", "impersonation")]
    finally:
        await svc.stop()


async def test_missing_client_is_an_error_check(make_services):
    svc = make_services(intercepta=None, tracer=None)
    await svc.start()
    try:
        d = await svc.pipeline.screen(req())
        assert d["verdict"] == "HOLD"
        assert "client unavailable" in check(d, "intercepta.quick_scan")["error"]
        assert check(d, "trace.source_of_funds")["status"] == "error"
    finally:
        await svc.stop()


# ---------- idempotency ----------


async def test_identical_request_within_10s_returns_same_case(make_services):
    svc = make_services()
    await svc.start()
    try:
        a = await svc.pipeline.screen(req())
        b = await svc.pipeline.screen(req())
        assert a["case_id"] == b["case_id"]
        c = await svc.pipeline.screen(req(amount="60000"))
        assert c["case_id"] != a["case_id"]
        d = await svc.pipeline.screen(req(resource="http://localhost:4022/v1/market-data"))
        assert d["case_id"] != a["case_id"]
        with svc.store._lock:  # age the idempotency row past the 10 s window
            svc.store._conn.execute("UPDATE idempotency SET created_ts = created_ts - 11")
        e = await svc.pipeline.screen(req())
        assert e["case_id"] != a["case_id"]
    finally:
        await svc.stop()


async def test_concurrent_identical_requests_share_one_case(make_services, fakes):
    fakes.intercepta.quick[CLEAN.lower()] = 0.2  # slow enough to overlap
    svc = make_services()
    await svc.start()
    try:
        results = await asyncio.gather(*(svc.pipeline.screen(req()) for _ in range(5)))
        assert len({r["case_id"] for r in results}) == 1
        assert len(svc.store.list_cases()[0]) == 1
        assert sum(1 for c in fakes.intercepta.calls if c[0] == "quick_scan") == 1
    finally:
        await svc.stop()


# ---------- background ----------


async def test_background_note_and_deep_scan_do_not_touch_the_hash(make_services, fakes):
    mixer = load_fixture("mixer_quick_scan.json")
    fakes.intercepta.quick[MIXER.lower()] = score_outcome("intercepta.quick_scan", mixer)
    fakes.intercepta.deep[MIXER.lower()] = score_outcome("intercepta.deep_scan", mixer)
    svc = make_services()
    await svc.start()
    try:
        d = await svc.pipeline.screen(req(MIXER))
        assert d["verdict"] == "HOLD" and d["analyst"] is None
        await settle(svc)
        row = svc.store.get_case(d["case_id"])
        stored = svc.store.get_report(d["report_hash"])
        assert "0x" + keccak(stored).hex() == d["report_hash"] == row["report_hash"]
        assert "deep_scan" not in stored.decode()
        view = svc.notifier.decision(d["case_id"])
        assert view["analyst"]["provider"] == "template" and view["analyst"]["fallback"] is True
        assert view["verdict"] == "HOLD" and view["report_hash"] == d["report_hash"]
        deep = check(view, "intercepta.deep_scan")
        assert deep["status"] == "ok" and deep["evidence_id"] == "E6"
    finally:
        await svc.stop()


async def test_block_is_refused_at_decision_time(make_services, fakes):
    fakes.intercepta.quick[SANCTIONED.lower()] = score_outcome(
        "intercepta.quick_scan", load_fixture("sanctioned_quick_scan.json"))
    svc = make_services()
    await svc.start()
    try:
        d = await svc.pipeline.screen(req(SANCTIONED))
        assert d["verdict"] == "BLOCK" and d["status"] == "REFUSED"
        assert ("deep_scan", SANCTIONED) not in fakes.intercepta.calls
    finally:
        await svc.stop()


@pytest.mark.parametrize("changed", [
    {"agent_id": "another-agent"}, {"source": "mcp"},
    {"purpose": "different purchase"}, {"untrusted_context": "different input"},
])
async def test_dedup_binds_complete_request(make_services, changed):
    svc = make_services()
    await svc.start()
    try:
        first = await svc.pipeline.screen(req())
        second = await svc.pipeline.screen(req(**changed))
        assert first["case_id"] != second["case_id"]
    finally:
        await svc.stop()


async def test_new_officer_block_invalidates_cached_allow(make_services):
    svc = make_services()
    await svc.start()
    try:
        first = await svc.pipeline.screen(req())
        assert first["verdict"] == "ALLOW"
        svc.store.put_override(CLEAN, "BLOCK", 4_102_444_800, "cs_OFFICER", None)
        second = await svc.pipeline.screen(req())
        assert second["case_id"] != first["case_id"]
        assert second["verdict"] == "BLOCK"
    finally:
        await svc.stop()


@pytest.mark.parametrize("changed", [
    {"asset": "0x4444444444444444444444444444444444444444"},
    {"payment_chain_id": 1}, {"payment_chain_id": 8453, "asset": BASE_USDC},
])
async def test_unsupported_payment_rejected_before_scanning(make_services, fakes, changed):
    svc = make_services()
    await svc.start()
    try:
        with pytest.raises(ValueError, match="Base Sepolia USDC"):
            await svc.pipeline.screen(req(**changed))
        assert not fakes.intercepta.calls
        assert not svc.store.list_cases()[0]
    finally:
        await svc.stop()


async def test_policy_change_invalidates_cached_case(make_services):
    svc = make_services()
    await svc.start()
    try:
        first = await svc.pipeline.screen(req())
        svc.policy.id = "0x" + "ab" * 32
        second = await svc.pipeline.screen(req())
        assert second["case_id"] != first["case_id"]
        assert second["policy"]["id"] == svc.policy.id
    finally:
        await svc.stop()


async def test_officer_block_while_checks_pending_is_applied(make_services, monkeypatch):
    svc = make_services()
    entered, resume = asyncio.Event(), asyncio.Event()
    run_checks = svc.pipeline.run_checks

    async def wait_checks(request):
        entered.set()
        await resume.wait()
        return await run_checks(request)

    monkeypatch.setattr(svc.pipeline, "run_checks", wait_checks)
    await svc.start()
    try:
        pending = asyncio.create_task(svc.pipeline.screen(req()))
        await entered.wait()
        svc.store.put_override(CLEAN, "BLOCK", 4_102_444_800, "cs_OFFICER", None)
        resume.set()
        result = await pending
        assert result["verdict"] == "BLOCK"
    finally:
        resume.set()
        await svc.stop()


def test_unknown_valuation_cannot_be_misrepresented_as_zero():
    from sekisho_gate.util import amount_to_usd

    with pytest.raises(ValueError, match="Unknown payment asset valuation"):
        amount_to_usd("1000000", 84532, "0x4444444444444444444444444444444444444444")
    with pytest.raises(ValueError, match="Unknown payment asset valuation"):
        amount_to_usd("1000000", 1, req().asset, req().asset)
    assert amount_to_usd("1000000", 84532, req().asset) == 1.0
    assert amount_to_usd("1000000", 8453, BASE_USDC) == 1.0  # read-only valuation
