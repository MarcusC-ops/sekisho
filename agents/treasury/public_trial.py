"""Opt-in, bounded public Base Sepolia trial. Run uvicorn with --factory create_app.

A single durable SQLite volume must be shared by all workers. Reservations never
expire or refund automatically: an interrupted signature may still be settled.
No operator routes, arbitrary URLs, raw process output, or escrow signing are exposed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import httpx
from pydantic import BaseModel, ConfigDict, Field

ATOMIC = 50_000
USDC = "0x036cbd53842c5426634e7929541ec2318f3dcf7e"


@dataclass(frozen=True)
class TrialConfig:
    enabled: bool = False
    db_path: str = "gate/public-trial.db"
    origin: str = "http://localhost:3112"
    max_runs: int = 20
    max_session_runs: int = 3
    max_ip_runs: int = 6
    max_atomic: int = 1_000_000
    clean_url: str = "http://127.0.0.1:4021/v1/market-data"
    flagged_url: str = "http://127.0.0.1:4023/v1/market-data"
    verified: bool = False

    @classmethod
    def from_env(cls):
        return cls(enabled=os.getenv("PUBLIC_TRIAL_ENABLED") == "true",
                   db_path=os.getenv("PUBLIC_TRIAL_DB_PATH", "gate/public-trial.db"),
                   origin=os.getenv("PUBLIC_TRIAL_ORIGIN", "http://localhost:3112"),
                   clean_url=os.getenv("PUBLIC_TRIAL_CLEAN_URL", cls.clean_url),
                   flagged_url=os.getenv("PUBLIC_TRIAL_FLAGGED_URL", cls.flagged_url),
                   verified=os.getenv("PUBLIC_TRIAL_LIVE_VERIFIED") == "true")


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal["clean", "flagged"]
    session_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{32,128}$")
    idempotency_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{16,128}$")


def reject(status, code, message):
    raise HTTPException(status, detail={"code": code, "message": message})


class Store:
    def __init__(self, config: TrialConfig):
        self.config = config
        Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS trial_runs (
                id TEXT PRIMARY KEY, session TEXT NOT NULL, idem TEXT NOT NULL,
                ip TEXT NOT NULL, scenario TEXT NOT NULL, status TEXT NOT NULL,
                created REAL NOT NULL, finished REAL, result TEXT, error TEXT,
                UNIQUE(session, idem))""")
        os.chmod(config.db_path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.config.db_path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def public(row):
        return {"run_id": row["id"], "scenario": row["scenario"], "status": row["status"],
                "created_at": row["created"], "finished_at": row["finished"],
                "result": json.loads(row["result"]) if row["result"] else None, "error": row["error"]}

    def reserve(self, body: RunRequest, ip: str):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM trial_runs WHERE session=? AND idem=?",
                                  (body.session_id, body.idempotency_key)).fetchone()
            if previous:
                if previous["scenario"] != body.scenario:
                    reject(409, "idempotency_conflict", "This request key already belongs to another scenario.")
                return self.public(previous), False
            count = db.execute("SELECT COUNT(*) FROM trial_runs").fetchone()[0]
            if count >= self.config.max_runs or (count + 1) * ATOMIC > self.config.max_atomic:
                reject(429, "trial_budget_exhausted", "The hosted trial allowance has been used.")
            for column, value, limit in (("session", body.session_id, self.config.max_session_runs),
                                         ("ip", ip, self.config.max_ip_runs)):
                if db.execute(f"SELECT COUNT(*) FROM trial_runs WHERE {column}=?", (value,)).fetchone()[0] >= limit:
                    reject(429, "trial_limit", "This visitor has reached the trial allowance.")
            if db.execute("SELECT 1 FROM trial_runs WHERE status='running'").fetchone():
                reject(409, "run_in_progress", "Another trial is running. Please try again shortly.")
            rid = secrets.token_urlsafe(32)
            db.execute("INSERT INTO trial_runs VALUES (?,?,?,?,?,'running',?,NULL,NULL,NULL)",
                       (rid, body.session_id, body.idempotency_key, ip, body.scenario, time.time()))
            db.commit()
            return self.get(rid), True

    def get(self, rid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM trial_runs WHERE id=?", (rid,)).fetchone()
        if row is None:
            reject(404, "not_found", "No trial with that capability exists.")
        return self.public(row)

    def finish(self, rid, status, result=None, error=None):
        with self.connect() as db:
            db.execute("UPDATE trial_runs SET status=?, result=?, error=?, finished=? WHERE id=? AND status='running'",
                       (status, json.dumps(result) if result else None, error, time.time(), rid))



async def verify_public_settlement(case, tx_hash, settings, buyer, destination):
    # Gate persistence is the uniqueness authority; a reused receipt is rejected there.
    if (case.get("status") != "PAID" or str(case.get("payment_tx") or "").lower() != tx_hash.lower()
            or case.get("payment_chain_id") != 84532):
        return False
    from sekisho_gate.receipts import verify_payment_receipt
    try:
        timestamp = int(datetime.fromisoformat(case["decided_at"].replace("Z", "+00:00")).timestamp())
        await verify_payment_receipt(settings.contracts_rpc_url, tx_hash, chain_id=84532,
            token=USDC, payer=buyer, payee=destination, amount=ATOMIC, min_timestamp=timestamp)
        return True
    except Exception:
        return False


class LiveRunner:
    def __init__(self, config, settings):
        self.config, self.settings = config, settings

    def blockers(self):
        s = self.settings
        missing = []
        for name in ("intercepta_api_key", "mb_admin_api_key", "buyer_agent_pk", "gate_screener_pk"):
            if not getattr(s, name).get_secret_value():
                missing.append({"code": name.upper(), "message": f"Server {name.upper()} is not configured."})
        for name in ("vendor_clean_payto", "vendor_sanctioned_payto", "mb_url"):
            if not getattr(s, name):
                missing.append({"code": name.upper(), "message": f"Server {name.upper()} is not configured."})
        if s.chain_id != 84532 or s.x402_network != "eip155:84532" or s.usdc_address.lower() != USDC:
            missing.append({"code": "TESTNET_REQUIRED", "message": "Only Base Sepolia test USDC is supported."})
        if not s.always_live_direct:
            missing.append({"code": "LIVE_SCAN_REQUIRED", "message": "Direct screening must use live provider data."})
        # Read-only quota check, sharing the gate's persistent DB. Leave headroom for
        # the two-sided scan and trace. The runner's lifetime cap is separately durable.
        try:
            with sqlite3.connect(f"file:{s.db_path}?mode=ro", uri=True) as db:
                row = db.execute("SELECT value FROM quota WHERE name='intercepta_calls'").fetchone()
            used = int(row[0]) if row else 0
            if used + 50 > min(s.intercepta_quota, s.intercepta_reserve_from):
                missing.append({"code": "PROVIDER_QUOTA", "message": "Provider quota headroom is reserved for the operator demo."})
        except sqlite3.Error:
            missing.append({"code": "QUOTA_UNAVAILABLE", "message": "Start the gate with persistent quota storage before public trials."})
        if s.fault_inject:
            missing.append({"code": "FAULT_INJECTION", "message": "Disable fault injection before live trials."})
        if not self.config.verified:
            missing.append({"code": "LIVE_VERIFICATION_REQUIRED", "message": "Operator must verify services, contracts, API access and testnet funds before enabling public trials."})
        return missing

    async def __call__(self, scenario, run_id):
        from agents.treasury.tools import TreasuryTools, build_x402_client, buyer_account, fget
        from sekisho import CURRENT, SekishoClient
        from sekisho_gate.chain.multibaas import MultiBaasClient
        from x402.schemas import AbortResult
        import httpx

        s = self.settings
        destination = s.vendor_clean_payto if scenario == "clean" else s.vendor_sanctioned_payto
        url = self.config.clean_url if scenario == "clean" else self.config.flagged_url

        class PublicTools(TreasuryTools):
            def _guard_before_sign(self, ctx):
                selected = fget(ctx, "selected_requirements")
                try:
                    decision = (CURRENT.get(None) or {}).get("decision")
                    decided = datetime.fromisoformat(fget(decision, "decided_at").replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - decided).total_seconds()
                    checks = fget(decision, "checks") or []
                    direct = next((c for c in checks if fget(c, "name") == "intercepta.quick_scan"), None)
                    if fget(direct, "status") != "ok" or fget(direct, "live") is not True:
                        raise ValueError("live direct screening required")
                    if not 0 <= age <= 120:
                        raise ValueError("stale decision")
                except (ValueError, TypeError, AttributeError):
                    return AbortResult(reason="HOLD|stale|A recent screening decision is required")
                if (str(fget(selected, "pay_to")).lower() != destination.lower()
                        or str(fget(selected, "amount")) != str(ATOMIC)
                        or str(fget(selected, "asset")).lower() != USDC
                        or fget(selected, "network") != "eip155:84532"):
                    return AbortResult(reason="HOLD|preset|Payment does not match the approved trial terms")
                if self._reserved_usdc:
                    return AbortResult(reason="HOLD|budget|Only one authorization is allowed per trial")
                return super()._guard_before_sign(ctx)

            async def _hold_in_escrow(self, case_id, case_b32, pay_to, amount, headline):
                return {"status": "held", "verdict": "HOLD", "case_id": case_id,
                        "escrow": False, "reason": str(headline)}

        sk, mb, buyer = SekishoClient(s.sekisho_url), MultiBaasClient(s), buyer_account(s)
        agent_id = "public-" + hashlib.sha256(run_id.encode()).hexdigest()
        tool = PublicTools(sk=sk, mb=mb, buyer=buyer, settings=s,
                           x402_client=build_x402_client(buyer, sk, agent_id), agent_id=agent_id,
                           vendors=[{"id": scenario, "name": "Trial vendor", "url": url}], emit=lambda _: None)
        try:
            raw = await tool.buy_data(scenario, "ETH-JPY")
            result = {k: raw.get(k) for k in ("status", "verdict", "case_id", "tx_hash")}
            result["reason"] = {"held": "Signing paused for review; no escrow deposit was attempted.",
                                "blocked": "Payment signing was refused.", "paid": "Payment receipt confirmed.",
                                "unconfirmed": "Payment settlement is not confirmed."}.get(raw.get("status"), "The live attempt did not complete a confirmed payment.")
            if result.get("status") == "paid" and not raw.get("case_id"):
                result.update(status="unconfirmed", reason="No gate case is available to verify this payment.")
            if raw.get("case_id"):
                case = await sk.get_case(raw["case_id"])
                if result.get("status") == "paid" and not await verify_public_settlement(
                        case, raw["tx_hash"], s, buyer.address, destination):
                    result.update(status="unconfirmed", reason="Payment has not passed independent receipt and case verification.")
                result["settlement_reason"] = result["reason"]
                result["headline"] = case.get("headline")
                if isinstance(case.get("headline"), str) and case["headline"]:
                    result["reason"] = case["headline"]
                result["reasons"] = case.get("reasons", [])
                result["checks"] = [{k: c.get(k) for k in ("name", "status", "live", "summary")} for c in case.get("checks", [])]
                result["triggered_rules"] = case.get("policy", {}).get("triggered_rules", [])
                result["report_hash"] = case.get("report_hash")
                result["case"] = {key: case.get(key) for key in (
                    "case_id", "verdict", "counterparty", "amount", "asset", "payment_chain_id",
                    "status", "decided_at", "report_hash", "policy")}
                # Return exact canonical bytes as UTF-8, never a reserialized report.
                report_hash = case.get("report_hash")
                if isinstance(report_hash, str) and len(report_hash) == 66:
                    from eth_utils import keccak
                    async with httpx.AsyncClient(timeout=15) as http:
                        response = await http.get(s.sekisho_url.rstrip("/") + "/v1/reports/" + report_hash)
                        response.raise_for_status()
                    if len(response.content) <= 512_000:
                        result["canonical_report"] = response.content.decode("utf-8")
                        result["report_hash_verified"] = "0x" + keccak(response.content).hex() == report_hash.lower()
                if result.get("status") == "paid":
                    # The report is the purchased JSON data; plain text is never executed.
                    result["purchased_data"] = raw.get("data")
            return result
        finally:
            await tool.aclose()


def create_app(config=None, runner=None, *, webhook_transport=None):
    config = config or TrialConfig.from_env()
    if runner is None:
        from sekisho_gate.config import get_settings
        runner = LiveRunner(config, get_settings())
    store = Store(config)
    tasks = set()

    @asynccontextmanager
    async def lifespan(app):
        yield
        for task in list(tasks):
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="Sekisho public trial", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=[config.origin], allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.post("/webhooks/multibaas")
    async def forward_multibaas_webhook(request: Request):
        # The private gate remains the HMAC verification authority. Only this
        # exact webhook path is exposed; neither destination nor path is input.
        max_bytes = 1_048_576
        timestamp = request.headers.get("x-multibaas-timestamp", "")
        signature = request.headers.get("x-multibaas-signature", "")
        if not timestamp or not signature or len(timestamp) > 32 or len(signature) > 128:
            reject(401, "unauthorized", "Missing or invalid webhook signature headers.")
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                size = int(content_length)
            except ValueError:
                reject(400, "invalid_request", "Invalid content length.")
            if size < 0:
                reject(400, "invalid_request", "Invalid content length.")
            if size > max_bytes:
                reject(413, "payload_too_large", "Webhook exceeds the body limit.")

        async def bounded_body():
            chunks, total = [], 0
            async for chunk in request.stream():
                total += len(chunk)
                if total > max_bytes:
                    reject(413, "payload_too_large", "Webhook exceeds the body limit.")
                chunks.append(chunk)
            return b"".join(chunks)

        try:
            raw_body = await asyncio.wait_for(bounded_body(), timeout=5.0)
        except asyncio.TimeoutError:
            reject(408, "request_timeout", "Webhook body was not received in time.")
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False, trust_env=False,
                                         transport=webhook_transport) as http:
                response = await http.post("http://127.0.0.1:8000/webhooks/multibaas", content=raw_body,
                    headers={"Content-Type": "application/json", "X-MultiBaas-Timestamp": timestamp,
                             "X-MultiBaas-Signature": signature})
        except httpx.TimeoutException:
            reject(504, "gate_timeout", "Webhook verification timed out.")
        except httpx.HTTPError:
            reject(502, "gate_unavailable", "Webhook verifier is unavailable.")
        return Response(content=response.content, status_code=response.status_code,
                        headers={"Content-Type": response.headers.get("content-type", "application/json")})

    def readiness():
        blockers = runner.blockers()
        if not config.enabled:
            blockers.insert(0, {"code": "DISABLED", "message": "Live public trials are not enabled yet."})
        return {"ready": not blockers, "mode": "unavailable" if blockers else "live", "network": "Base Sepolia",
                "blockers": blockers, "scenarios": [{"id": "clean", "label": "Standard vendor", "amount_usdc": "0.05"},
                    {"id": "flagged", "label": "Flagged recipient", "amount_usdc": "0.05"}]}

    @app.get("/public/readiness")
    async def ready():
        return readiness()

    async def execute(record):
        try:
            result = await asyncio.wait_for(runner(record["scenario"], record["run_id"]), timeout=180)
            store.finish(record["run_id"], "completed", result=result)
        except asyncio.CancelledError:
            store.finish(record["run_id"], "interrupted", error="Service stopped. Reservation retained; do not replay without reconciliation.")
            raise
        except Exception:
            store.finish(record["run_id"], "failed", error="The live attempt could not be confirmed. Reservation retained.")

    @app.post("/public/runs", status_code=202)
    async def start(body: RunRequest, request: Request):
        if request.headers.get("origin") not in (None, config.origin):
            reject(403, "origin_denied", "This origin cannot start trials.")
        if not readiness()["ready"]:
            reject(503, "live_unavailable", "Live prerequisites are not ready. Use the labelled walkthrough.")
        # Never trust visitor-supplied X-Forwarded-For. Configure proxy trust at the server.
        ip = hashlib.sha256((request.client.host if request.client else "unknown").encode()).hexdigest()
        record, fresh = store.reserve(body, ip)
        if fresh:
            task = asyncio.create_task(execute(record))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        return record

    @app.get("/public/runs/{run_id}")
    async def get(run_id: str):
        return store.get(run_id)

    return app
