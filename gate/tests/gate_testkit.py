"""Test kit for the gate tests: fake clients, synthetic Intercepta fixtures, webhook
signing and small helpers. Imported by conftest.py and the test modules.

Fakes and respx exist only in tests. The running gate has no mock mode.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from eth_utils import keccak

from sekisho_gate.screening.types import CheckOutcome

DATA = Path(__file__).parent / "data"

CLEAN = "0x1111111111111111111111111111111111111111"
MIXER = "0x2222222222222222222222222222222222222222"
SANCTIONED = "0x098B716B8Aaf21512996dC57EB0615e2383E2f96"
BASE_SEPOLIA_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WEBHOOK_SECRET = "whsec_test_secret"


def load_fixture(name: str) -> dict[str, Any]:
    """A synthetic (or, later, captured) Intercepta response: the wrapper's `response`."""
    return json.loads((DATA / "intercepta" / name).read_text(encoding="utf-8"))["response"]


def score_outcome(name: str, body: dict[str, Any], *, live: bool = True) -> CheckOutcome:
    traits = body["traits"]
    return CheckOutcome(
        name=name, status="ok", live=live, latency_ms=120,
        summary=f"toxicScore {body['toxicScore']}, {len(traits)} traits",
        data={"toxicScore": body["toxicScore"], "traits": traits}, raw=body,
    )


def oracle_outcome(eth: bool | None, base: bool | None) -> CheckOutcome:
    data = {"1": eth, "8453": base}
    return CheckOutcome(
        name="sanctions.oracle", status="ok" if None not in (eth, base) else "error", latency_ms=90,
        summary="", data=data, raw={"1": {"result": str(eth)}, "8453": {"result": str(base)}},
        error=None if None not in (eth, base) else "one chain failed",
    )


def trace_outcome(taint_pct: float = 0.0, paths: list[str] | None = None) -> CheckOutcome:
    data = {
        "chains": [1, 8453], "inbound_usd_traced": 1000.0,
        "hop1": [{"address": CLEAN, "chain_id": 1, "usd": 1000.0, "share_pct": 100.0, "tx_count": 2,
                  "labels": [], "flags": [], "sanctioned": False, "intercepta": None}],
        "hop2": [], "taint_pct": taint_pct, "paths": paths or [], "truncated": False,
        "notes": ["synthetic trace (test fake)"],
    }
    return CheckOutcome(name="trace.source_of_funds", status="ok", latency_ms=300,
                        summary=f"taint {taint_pct}%", data=data, raw={"synthetic": True})


def error_outcome(name: str, error: str = "boom") -> CheckOutcome:
    return CheckOutcome(name=name, status="error", latency_ms=5, summary=error, error=error)


# ---------- fakes ----------


class FakeIntercepta:
    """Per-address responses; a value may be a CheckOutcome, an Exception to raise, or a
    float (seconds to hang, to exercise timeouts)."""

    def __init__(self) -> None:
        self.quick: dict[str, Any] = {}
        self.deep: dict[str, Any] = {}
        self.imp: dict[str, Any] = {}
        self.token: Any = None
        self.calls: list[tuple[str, str]] = []
        self.used = 0

    async def _answer(self, kind: str, table: dict[str, Any] | Any, address: str, default: Any) -> CheckOutcome:
        self.calls.append((kind, address))
        self.used += 1
        value = table.get(address.lower(), default) if isinstance(table, dict) else (table or default)
        if isinstance(value, float):
            await asyncio.sleep(value)
            value = default
        if isinstance(value, Exception):
            raise value
        return value

    async def quick_scan(self, address: str, *, live: bool = True) -> CheckOutcome:
        return await self._answer("quick_scan", self.quick, address,
                                  score_outcome("intercepta.quick_scan", {"toxicScore": 0, "traits": []}))

    async def quick_scan_cached(self, address: str) -> CheckOutcome:
        return await self.quick_scan(address, live=False)

    async def deep_scan(self, address: str, *, live: bool = False) -> CheckOutcome:
        return await self._answer("deep_scan", self.deep, address,
                                  score_outcome("intercepta.deep_scan", {"toxicScore": 0, "traits": []}))

    async def impersonation(self, address: str, *, live: bool = False) -> CheckOutcome:
        body = load_fixture("impersonation_clean.json")
        return await self._answer("impersonation", self.imp, address, CheckOutcome(
            name="intercepta.impersonation", status="ok", live=False, latency_ms=80,
            summary="not a poisoning lookalike", data=body, raw=body))

    async def token_scan(self, token_address: str, chain_id: int = 8453) -> CheckOutcome:
        self.calls.append(("token", f"{chain_id}:{token_address}"))
        if self.token is not None:
            if isinstance(self.token, Exception):
                raise self.token
            return self.token
        body = load_fixture("token_base_usdc.json")
        data = {k: body[k] for k in ("riskScore", "riskLevel", "trust", "action")}
        data["detectors"] = body["detectors"]
        return CheckOutcome(name="intercepta.token", status="ok", live=False, latency_ms=70,
                            summary="action info", data=data, raw=body)

    def quota_status(self) -> dict[str, int]:
        return {"used": self.used, "quota": 1000, "remaining": 1000 - self.used, "warn_at": 800, "reserve_from": 950}

    def key_status(self) -> tuple[bool, str]:
        return True, "key valid (fake)"

    async def aclose(self) -> None:
        pass


class FakeOracle:
    def __init__(self) -> None:
        self.answers: dict[str, Any] = {SANCTIONED.lower(): oracle_outcome(True, True)}
        self.calls: list[str] = []

    async def check(self, address: str) -> CheckOutcome:
        self.calls.append(address)
        value = self.answers.get(address.lower(), oracle_outcome(False, False))
        if isinstance(value, float):
            await asyncio.sleep(value)
            value = oracle_outcome(False, False)
        if isinstance(value, Exception):
            raise value
        return value

    async def self_test(self) -> tuple[bool, str]:
        return True, "0x098B…2F96 sanctioned on 1 (fake)"

    async def aclose(self) -> None:
        pass


class FakeTracer:
    def __init__(self) -> None:
        self.answers: dict[str, Any] = {}

    async def trace(self, address: str) -> CheckOutcome:
        value = self.answers.get(address.lower(), trace_outcome(0.0))
        if isinstance(value, float):
            await asyncio.sleep(value)
            value = trace_outcome(0.0)
        if isinstance(value, Exception):
            raise value
        return value

    async def aclose(self) -> None:
        pass


class FakeMBError(Exception):
    """Same attributes as chain.multibaas.MultiBaasError."""

    def __init__(self, message: str, *, status: int | None = 400, body: str = "", revert: str | None = None,
                 selector: str | None = None):
        super().__init__(message)
        self.status, self.body, self.revert, self.selector = status, body, revert, selector


class FakeMultiBaas:
    """Records writes; tracks per-signer open transactions (sent, receipt not yet
    awaited) so tests can assert the single nonce lane."""

    configured = True

    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []
        self.reverts: dict[str, FakeMBError] = {}
        self.receipt_status: dict[str, int] = {}
        self.write_delay = 0.005
        self.receipt_delay = 0.01
        self.open: dict[str, int] = defaultdict(int)
        self.max_open: dict[str, int] = defaultdict(int)
        self.tx_info: dict[str, dict[str, Any]] = {}
        self.events_by_tx: dict[str, list[dict[str, Any]]] = {}
        self.reads: dict[tuple[str, str], Any] = {}
        self.queries: dict[str, Any] = {}

    async def call_write(self, alias: str, label: str, method: str, args: list, signer: Any) -> str:
        who = signer.address
        self.open[who] += 1
        self.max_open[who] = max(self.max_open[who], self.open[who])
        await asyncio.sleep(self.write_delay)
        if method in self.reverts:
            self.open[who] -= 1
            raise self.reverts[method]
        tx = "0x" + keccak(text=f"{len(self.writes)}:{method}:{who}").hex()
        self.writes.append({"alias": alias, "label": label, "method": method, "args": args, "from": who, "tx": tx})
        self.tx_info[tx] = {"method": method, "from": who}
        return tx

    async def wait_for_receipt(self, tx_hash: str, timeout_s: float = 30.0) -> dict[str, Any]:
        await asyncio.sleep(self.receipt_delay)
        info = self.tx_info[tx_hash]
        self.open[info["from"]] -= 1
        return {"status": self.receipt_status.get(info["method"], 1), "blockNumber": 100 + len(self.writes)}

    async def call_read(self, alias: str, label: str, method: str, args: list) -> Any:
        value = self.reads.get((alias, method))
        if isinstance(value, Exception):
            raise value
        return value

    async def list_events(self, *, tx_hash: str | None = None, contract_alias: str | None = None, limit: int = 20):
        return self.events_by_tx.get(tx_hash, [])

    async def query_results(self, name: str) -> list[dict[str, Any]]:
        value = self.queries.get(name, [])
        if isinstance(value, Exception):
            raise value
        return value

    async def address_of(self, alias: str) -> str:
        return "0x3333333333333333333333333333333333333333"

    async def health(self) -> tuple[bool, str]:
        return True, "reachable (fake)"

    async def aclose(self) -> None:
        pass


class FakeLLM:
    provider = "anthropic"
    model = "fake-model"
    configured = True

    def __init__(self, reply: Any = None, delay: float = 0.0) -> None:
        self.reply = reply
        self.delay = delay
        self.prompts: list[tuple[str, str]] = []

    def status(self) -> tuple[bool, str]:
        return True, "anthropic fake-model"

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        self.prompts.append((system, user))
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.reply, Exception):
            raise self.reply
        return dict(self.reply)

    async def aclose(self) -> None:
        pass


# ---------- webhook signing (PRD 9.13) ----------


def sign_webhook(body: bytes, ts: str, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode(), body + ts.encode(), hashlib.sha256).hexdigest()


def _local_verify(body: bytes, timestamp: str, signature: str, secret: str) -> bool:
    return hmac.compare_digest(sign_webhook(body, timestamp, secret), signature)


def _local_parse_event(raw: dict[str, Any]) -> dict[str, Any]:
    ev, tx = raw.get("event") or {}, raw.get("transaction") or {}
    contract = ev.get("contract") or {}
    return {
        "name": ev.get("name"),
        "contract_alias": contract.get("addressAlias") or contract.get("addressLabel") or contract.get("label"),
        "contract_address": contract.get("address"),
        "tx_hash": tx.get("txHash"),
        "block_number": tx.get("blockNumber"),
        "log_index": ev.get("indexInLog"),
        "inputs": {i["name"]: i["value"] for i in ev.get("inputs") or []},
    }


def webhook_functions() -> tuple[Any, Any, str]:
    """The integrations agent's verify/parse when chain/multibaas.py exists, else local
    stand-ins with the PRD 9.13 formula."""
    try:
        from sekisho_gate.chain.multibaas import parse_event, verify_webhook_signature

        return verify_webhook_signature, parse_event, "chain.multibaas"
    except ImportError:
        return _local_verify, _local_parse_event, "local"


def mb_event(name: str, inputs: dict[str, Any], *, tx_hash: str, log_index: int = 0, block: int = 123,
             alias: str = "compliance_registry") -> dict[str, Any]:
    """A MultiBaas `event.emitted` delivery item (shape from the MultiBaas docs sample)."""
    contract = {"address": "0x9deE000000000000000000000000000000000D67", "addressAlias": alias,
                "addressLabel": alias, "name": name, "label": alias}
    return {
        "id": f"evt-{tx_hash[-6:]}-{log_index}",
        "event": "event.emitted",
        "data": {
            "triggeredAt": "2026-09-26T10:21:40+09:00",
            "event": {"name": name, "signature": f"{name}(...)",
                      "inputs": [{"name": k, "value": v, "hashed": False, "type": ""} for k, v in inputs.items()],
                      "rawFields": "{}", "contract": contract, "indexInLog": log_index},
            "transaction": {"from": "0x0000000000000000000000000000000000000001", "txData": "0x",
                            "txHash": tx_hash, "txIndexInBlock": 0, "blockHash": "0x" + "ab" * 32,
                            "blockNumber": block, "contract": contract},
        },
    }


def screen_body(counterparty: str = CLEAN, **overrides: Any) -> dict[str, Any]:
    body = {
        "counterparty": counterparty,
        "direction": "outbound",
        "amount": "50000",
        "asset": BASE_SEPOLIA_USDC,
        "payment_chain_id": 84532,
        "source": "x402",
        "agent_id": "treasury-agent-01",
        "purpose": "Buy ETH/JPY market data",
        "resource": "http://localhost:4021/v1/market-data",
        "untrusted_context": None,
    }
    body.update(overrides)
    return body


async def settle(svc: Any, rounds: int = 50) -> None:
    """Let background work (attestation lane, analyst, deep scan) finish."""
    for _ in range(rounds):
        await svc.pipeline.drain(timeout_s=1.0)
        lanes = (svc.attestor.screener_lane, svc.attestor.officer_lane)
        if all(lane.queue.empty() and lane.active == 0 for lane in lanes) and not svc.pipeline._background:
            return
        await asyncio.sleep(0.02)
