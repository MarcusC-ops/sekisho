"""Public API limits use real SQLite across clients/process-style store instances."""
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from fastapi.testclient import TestClient

from agents.treasury.public_trial import RunRequest, Store, TrialConfig, create_app


class Runner:
    def __init__(self):
        self.calls = 0

    def blockers(self):
        return []

    async def __call__(self, scenario, run_id):
        self.calls += 1
        return {"verdict": "BLOCK", "status": "blocked", "reason": "test provider response"}


def body(n=1, scenario="clean", session="s" * 32):
    return {"scenario": scenario, "session_id": session, "idempotency_key": str(n).zfill(16)}


def config(tmp_path, **kwargs):
    return TrialConfig(db_path=str(tmp_path / "trial.db"), **kwargs)


def test_disabled_does_not_invoke_runner(tmp_path):
    runner = Runner()
    with TestClient(create_app(config(tmp_path), runner)) as client:
        assert client.get("/public/readiness").json()["ready"] is False
        assert client.post("/public/runs", json=body()).status_code == 503
    assert runner.calls == 0


def test_isolated_capability_and_replay(tmp_path):
    runner = Runner()
    with TestClient(create_app(config(tmp_path, enabled=True), runner)) as client:
        first = client.post("/public/runs", json=body()).json()
        second = client.post("/public/runs", json=body()).json()
        assert first["run_id"] == second["run_id"]
        assert len(first["run_id"]) >= 40
        assert client.get("/public/runs/missing").status_code == 404
        assert client.post("/public/runs", json=body(scenario="flagged")).status_code == 409
        assert "session_id" not in first
    assert runner.calls == 1


def test_reject_extra_fields_and_wrong_origin(tmp_path):
    with TestClient(create_app(config(tmp_path, enabled=True), Runner())) as client:
        assert client.post("/public/runs", json={**body(), "pay_to": "0x123"}).status_code == 422
        assert client.post("/public/runs", json=body(), headers={"Origin": "https://evil.example"}).status_code == 403


def test_durable_budget_survives_restart_and_failed_runs(tmp_path):
    cfg = config(tmp_path, max_runs=10, max_atomic=50_000)
    store = Store(cfg)
    record, _ = store.reserve(RunRequest(**body()), "ip")
    store.finish(record["run_id"], "failed", error="failed")
    restarted = Store(cfg)
    assert restarted.reserve(RunRequest(**body()), "ip")[1] is False
    try:
        restarted.reserve(RunRequest(**body(2)), "ip")
    except HTTPException as exc:
        assert exc.status_code == 429
    else:
        raise AssertionError("failed run reservation refunded")


def test_crash_record_prevents_automatic_payment_replay(tmp_path):
    cfg = config(tmp_path)
    Store(cfg).reserve(RunRequest(**body()), "ip")
    try:
        Store(cfg).reserve(RunRequest(**body(2)), "ip")
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("crashed in-flight payment was silently replayed")


def test_atomic_concurrent_reservations(tmp_path):
    cfg = config(tmp_path)
    Store(cfg)
    def reserve(n):
        try:
            return Store(cfg).reserve(RunRequest(**body(n)), "ip")[1]
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, range(1, 5)))
    assert results.count(True) == 1
    assert results.count(409) == 3


def test_run_and_session_caps_survive_new_store(tmp_path):
    cfg = config(tmp_path, max_runs=2, max_session_runs=1)
    store = Store(cfg)
    record, _ = store.reserve(RunRequest(**body()), "ip")
    store.finish(record["run_id"], "completed", result={"verdict": "BLOCK"})
    for request in (body(2),):
        try:
            Store(cfg).reserve(RunRequest(**request), "ip")
        except HTTPException as exc:
            assert exc.status_code == 429
        else:
            raise AssertionError("session cap bypassed")
    second, _ = store.reserve(RunRequest(**body(2, session="x" * 32)), "ip")
    store.finish(second["run_id"], "completed", result={"verdict": "BLOCK"})
    try:
        Store(cfg).reserve(RunRequest(**body(3, session="z" * 32)), "ip")
    except HTTPException as exc:
        assert exc.detail["code"] == "trial_budget_exhausted"
    else:
        raise AssertionError("global API run quota bypassed")


def test_exception_details_never_exposed(tmp_path):
    class Failed(Runner):
        async def __call__(self, *args):
            raise RuntimeError("SECRET_API_KEY=do-not-leak")
    with TestClient(create_app(config(tmp_path, enabled=True), Failed())) as client:
        record = client.post("/public/runs", json=body()).json()
        for _ in range(20):
            state = client.get("/public/runs/" + record["run_id"])
            if state.json()["status"] == "failed":
                break
        assert state.json()["status"] == "failed"
        assert "SECRET" not in state.text


def test_replayed_receipt_requires_gate_paid_record():
    import asyncio
    from types import SimpleNamespace
    from agents.treasury.public_trial import verify_public_settlement
    settings = SimpleNamespace(contracts_rpc_url="https://must-not-be-called.invalid")
    tx = "0x" + "11" * 32
    for case in ({"status": "DECIDED"}, {"status": "PAID", "payment_tx": "other"},
                 {"status": "PAID", "payment_tx": tx, "payment_chain_id": 1}):
        assert asyncio.run(verify_public_settlement(case, tx, settings, "buyer", "payee")) is False


def test_settlement_uses_chain_timestamp_and_exact_terms(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from agents.treasury.public_trial import verify_public_settlement
    calls = []
    async def verify(url, tx, **kwargs):
        calls.append(kwargs)
    monkeypatch.setattr("sekisho_gate.receipts.verify_payment_receipt", verify)
    tx = "0x" + "11" * 32
    case = {"status": "PAID", "payment_tx": tx, "payment_chain_id": 84532, "decided_at": "2026-01-01T00:00:00Z"}
    assert asyncio.run(verify_public_settlement(case, tx, SimpleNamespace(contracts_rpc_url="unused"), "buyer", "payee"))
    assert calls[0]["chain_id"] == 84532
    assert calls[0]["min_timestamp"] == 1767225600
    assert calls[0]["amount"] == 50000
    async def stale(*args, **kwargs):
        raise ValueError("block predates current decision")
    monkeypatch.setattr("sekisho_gate.receipts.verify_payment_receipt", stale)
    assert not asyncio.run(verify_public_settlement(case, tx, SimpleNamespace(contracts_rpc_url="unused"), "buyer", "payee"))


def test_live_readiness_checks_durable_quota_and_live_mode(tmp_path):
    import sqlite3
    from pydantic import SecretStr
    from types import SimpleNamespace
    from agents.treasury.public_trial import LiveRunner
    path = tmp_path / "gate.db"
    settings = SimpleNamespace(intercepta_api_key=SecretStr("present"), mb_admin_api_key=SecretStr("present"),
        buyer_agent_pk=SecretStr("present"), gate_screener_pk=SecretStr("present"),
        vendor_clean_payto="present", vendor_sanctioned_payto="present", mb_url="present",
        chain_id=84532, x402_network="eip155:84532", usdc_address="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        db_path=path, intercepta_quota=1000, intercepta_reserve_from=950, always_live_direct=True, fault_inject="")
    runner = LiveRunner(config(tmp_path, enabled=True, verified=True), settings)
    assert "QUOTA_UNAVAILABLE" in [x["code"] for x in runner.blockers()]
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE quota(name TEXT, value INTEGER)")
        db.execute("INSERT INTO quota VALUES('intercepta_calls', 901)")
    assert "PROVIDER_QUOTA" in [x["code"] for x in runner.blockers()]
    with sqlite3.connect(path) as db:
        db.execute("UPDATE quota SET value=0")
    assert runner.blockers() == []
    settings.always_live_direct = False
    assert "LIVE_SCAN_REQUIRED" in [x["code"] for x in runner.blockers()]


def test_adapter_never_delivers_paid_claim_when_gate_rejected_receipt(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from agents.treasury.public_trial import LiveRunner
    import agents.treasury.tools as treasury
    import sekisho
    import sekisho_gate.chain.multibaas as multibaas
    class ToolBoundary:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
        async def buy_data(self, vendor, pair):
            assert vendor == "clean" and pair == "ETH-JPY"
            return {"status": "paid", "verdict": "ALLOW", "case_id": "case-1",
                    "tx_hash": "0x" + "11" * 32, "data": {"price": "test"}}
        async def aclose(self):
            pass
    class GateBoundary:
        async def get_case(self, case_id):
            return {"status": "DECIDED", "headline": "No adverse traits were found.",
                    "checks": [{"name": "intercepta.quick_scan", "live": True, "status": "ok", "summary": "Original provider text"}]}
    monkeypatch.setattr(treasury, "TreasuryTools", ToolBoundary)
    monkeypatch.setattr(treasury, "build_x402_client", lambda *args: object())
    monkeypatch.setattr(treasury, "buyer_account", lambda *args: SimpleNamespace(address="0x" + "22" * 20))
    monkeypatch.setattr(sekisho, "SekishoClient", lambda *args: GateBoundary())
    monkeypatch.setattr(multibaas, "MultiBaasClient", lambda *args: object())
    settings = SimpleNamespace(vendor_clean_payto="0x" + "33" * 20, sekisho_url="unused")
    result = asyncio.run(LiveRunner(TrialConfig(), settings)("clean", "test-run"))
    assert result["status"] == "unconfirmed"
    assert "purchased_data" not in result
    assert result["reason"] == "No adverse traits were found."
    assert result["checks"][0]["live"] is True
    assert result["checks"][0]["summary"] == "Original provider text"


def test_adapter_success_uses_real_case_view_schema_and_missing_case_fails_closed(monkeypatch):
    import asyncio
    import json
    from types import SimpleNamespace
    from agents.treasury.public_trial import LiveRunner
    from sekisho_gate.views import case_detail_view
    import agents.treasury.tools as treasury
    import sekisho
    import sekisho_gate.chain.multibaas as multibaas
    tx = "0x" + "11" * 32
    # Build the HTTP response with the production view; payment_network is not exposed.
    case = case_detail_view({"status": "PAID", "payment_tx": tx, "payment_chain_id": 84532,
        "decision_json": json.dumps({"case_id": "case-1", "verdict": "ALLOW", "checks": [],
            "decided_at": "2026-01-01T00:00:00Z", "headline": "Clear", "policy": {}})},
        [], "https://sepolia.basescan.org", validate=False)
    assert "payment_network" not in case
    raw = {"status": "paid", "verdict": "ALLOW", "case_id": "case-1", "tx_hash": tx, "data": {"price": "test"}}
    class ToolBoundary:
        def __init__(self, **kwargs):
            pass
        async def buy_data(self, vendor, pair):
            return raw
        async def aclose(self):
            pass
    class GateBoundary:
        async def get_case(self, case_id):
            return case
    async def receipt(*args, **kwargs):
        assert kwargs["chain_id"] == 84532
        assert kwargs["min_timestamp"] == 1767225600
    monkeypatch.setattr(treasury, "TreasuryTools", ToolBoundary)
    monkeypatch.setattr(treasury, "build_x402_client", lambda *args: object())
    monkeypatch.setattr(treasury, "buyer_account", lambda *args: SimpleNamespace(address="0x" + "22" * 20))
    monkeypatch.setattr(sekisho, "SekishoClient", lambda *args: GateBoundary())
    monkeypatch.setattr(multibaas, "MultiBaasClient", lambda *args: object())
    monkeypatch.setattr("sekisho_gate.receipts.verify_payment_receipt", receipt)
    settings = SimpleNamespace(vendor_clean_payto="0x" + "33" * 20, sekisho_url="unused", contracts_rpc_url="unused")
    result = asyncio.run(LiveRunner(TrialConfig(), settings)("clean", "test-run"))
    assert result["status"] == "paid"
    assert result["purchased_data"] == {"price": "test"}
    raw["case_id"] = None
    result = asyncio.run(LiveRunner(TrialConfig(), settings)("clean", "test-run-2"))
    assert result["status"] == "unconfirmed"
    assert "purchased_data" not in result


def webhook_headers(body, secret="test-only-webhook-secret"):
    import hashlib
    import hmac
    ts = "1790424000"
    return {"X-MultiBaas-Timestamp": ts,
            "X-MultiBaas-Signature": hmac.new(secret.encode(), body + ts.encode(), hashlib.sha256).hexdigest()}


def real_webhook_gate():
    from fastapi import FastAPI
    from types import SimpleNamespace
    from pydantic import SecretStr
    from sekisho_gate.webhooks import build_router
    from sekisho_gate.chain.multibaas import verify_webhook_signature
    gate = FastAPI()
    services = SimpleNamespace(settings=SimpleNamespace(mb_webhook_secret=SecretStr("test-only-webhook-secret")),
                               verify_webhook=verify_webhook_signature)
    gate.include_router(build_router(lambda: services))
    return gate


def test_webhook_proxy_preserves_exact_body_and_real_gate_auth(tmp_path):
    import httpx
    raw = b' [ \n ] '
    app = create_app(config(tmp_path), Runner(), webhook_transport=httpx.ASGITransport(app=real_webhook_gate()))
    with TestClient(app) as client:
        success = client.post("/webhooks/multibaas", content=raw, headers=webhook_headers(raw))
        assert success.status_code == 200 and success.json() == {"ok": True}
        forged = client.post("/webhooks/multibaas", content=raw, headers=webhook_headers(raw, "wrong-secret"))
        assert forged.status_code == 401
        malformed = b'not-json'
        bad_json = client.post("/webhooks/multibaas", content=malformed, headers=webhook_headers(malformed))
        assert bad_json.status_code == 400
        assert bad_json.json()["message"] == "body is not JSON"
        assert client.post("/webhooks/multibaas", content=raw).status_code == 401
        assert client.post("/v1/cases/example/decision", json={"action": "release"}).status_code == 404
        assert client.get("/webhooks/multibaas").status_code == 405


def test_webhook_oversize_is_rejected_before_gate(tmp_path):
    import httpx
    def never_forward(request):
        raise AssertionError("Oversized webhook reached gate")
    app = create_app(config(tmp_path), Runner(), webhook_transport=httpx.MockTransport(never_forward))
    with TestClient(app) as client:
        data = b'x' * 1_048_577
        assert client.post("/webhooks/multibaas", content=data, headers=webhook_headers(data)).status_code == 413
        # A dishonest length header cannot bypass actual byte counting.
        assert client.post("/webhooks/multibaas", content=data,
                           headers={**webhook_headers(data), "Content-Length": "1"}).status_code == 413


def test_webhook_downstream_status_and_headers_are_restricted(tmp_path):
    import httpx
    seen = []
    def downstream(request):
        seen.append(request)
        return httpx.Response(429, json={"error": "busy"}, headers={"Set-Cookie": "private=value"})
    app = create_app(config(tmp_path), Runner(), webhook_transport=httpx.MockTransport(downstream))
    with TestClient(app) as client:
        result = client.post("/webhooks/multibaas?target=https://evil.example", content=b'[]',
                             headers={**webhook_headers(b'[]'), "Authorization": "Bearer forbidden"})
        assert result.status_code == 429 and result.json() == {"error": "busy"}
        assert "set-cookie" not in result.headers
        assert str(seen[0].url) == "http://127.0.0.1:8000/webhooks/multibaas"
        assert "authorization" not in seen[0].headers


def test_webhook_downstream_timeout_and_connection_failure(tmp_path):
    import httpx
    for failure, expected in [(httpx.ReadTimeout("private details"), 504), (httpx.ConnectError("private details"), 502)]:
        def downstream(request):
            raise failure
        app = create_app(config(tmp_path), Runner(), webhook_transport=httpx.MockTransport(downstream))
        with TestClient(app) as client:
            response = client.post("/webhooks/multibaas", content=b'[]', headers=webhook_headers(b'[]'))
            assert response.status_code == expected
            assert "private details" not in response.text
