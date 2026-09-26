"""MultiBaas webhook receiver and chain-event handling (PRD 9.13).

POST /webhooks/multibaas: HMAC-verified (chain.multibaas.verify_webhook_signature), then
every `event.emitted` item is parsed (chain.multibaas.parse_event) and handled:

- upsert into chain_events, idempotent on txHash + indexInLog;
- Screened -> the case's attestation is confirmed (matched on caseId);
- Held -> hold linked to the case, status HELD_ESCROWED;
- Released / Refunded -> case status;
- VerdictOverridden -> audit log entry;
- SSE `chain.event` for new events and `case.updated` for the matched case.

P1 fallback poller: when a transaction we know about has had no event for 60 s,
fetch its events by tx hash (MultiBaas GET /events has no sort, so polling by
contract could return the oldest events) every 30 s.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .logs import case_id_var, get_logger
from .util import checksum_or_none, iso, json_int, norm_hex32

log = get_logger("sekisho.webhooks")

INT_INPUTS = {"verdict", "riskScore", "expiresAt", "previous", "next", "holdId", "amount"}
ADDRESS_INPUTS = {"subject", "screener", "officer", "payer", "payee", "by"}
BYTES32_INPUTS = {"reportHash", "policyId", "caseId", "noteHash"}
KNOWN_EVENTS = {"Screened", "VerdictOverridden", "Held", "Released", "Refunded"}

POLL_EVERY_S = 30.0
POLL_AFTER_S = 60.0
POLL_GIVE_UP_S = 3600.0
POLL_MAX_TXS = 10


def normalise_inputs(inputs: Any) -> dict[str, Any]:
    """Solidity parameter names; ints as JSON numbers below 2^53 (else decimal strings),
    addresses checksummed, bytes32 as 0x + lowercase hex."""
    if isinstance(inputs, list):  # [{name, value}] as MultiBaas sends it
        inputs = {i.get("name"): i.get("value") for i in inputs if isinstance(i, dict)}
    out: dict[str, Any] = {}
    for name, value in (inputs or {}).items():
        if name in INT_INPUTS:
            out[name] = json_int(value)
        elif name in ADDRESS_INPUTS:
            out[name] = checksum_or_none(value) or value
        elif name in BYTES32_INPUTS:
            out[name] = norm_hex32(value) or value
        else:
            out[name] = value
    return out


class ChainEventHandler:
    def __init__(self, *, store: Any, notifier: Any, explorer_url: str):
        self.store = store
        self.notifier = notifier
        self.explorer_url = explorer_url

    def handle(self, ev: dict[str, Any], source: str = "webhook") -> dict[str, Any] | None:
        """`ev` is a parse_event() dict. Returns the ChainEvent view, or None if skipped."""
        from .views import chain_event_view

        name = ev.get("name")
        tx = norm_hex32(ev.get("tx_hash"))
        if not name or not tx:
            log.warning("chain event without name or tx hash", extra={"event": str(ev)[:300]})
            return None
        log_index = int(ev.get("log_index") or 0)
        inputs = normalise_inputs(ev.get("inputs"))
        b32 = norm_hex32(inputs.get("caseId"))
        case = self.store.get_case_by_b32(b32) if b32 else None
        case_id = case["case_id"] if case else None
        token = case_id_var.set(case_id)
        try:
            row = {
                "event_uid": f"{tx}:{log_index}",
                "name": name,
                "contract_alias": ev.get("contract_alias"),
                "contract_address": ev.get("contract_address"),
                "tx_hash": tx,
                "block_number": ev.get("block_number"),
                "log_index": log_index,
                "inputs": inputs,
                "case_id": case_id,
                "case_id_b32": b32,
                "source": source,
                "received_at": iso(),
            }
            is_new = self.store.upsert_chain_event(row)
            changed = self._apply(case, name, tx, inputs, is_new) if case else False
            view = chain_event_view(row, self.explorer_url)
            if is_new:
                log.info("chain event", extra={"event": name, "tx_hash": tx, "source": source})
                self.notifier.chain_event(view)
            if case and (is_new or changed):
                self.notifier.case_updated(case_id, metrics=name == "Screened")
            return view
        finally:
            case_id_var.reset(token)

    def _apply(self, case: dict[str, Any], name: str, tx: str, inputs: dict[str, Any], is_new: bool) -> bool:
        """Idempotent case updates. Returns True if the case row changed."""
        cid = case["case_id"]
        status = case["status"]
        hold_id = inputs.get("holdId")
        if name == "Screened":
            if case.get("attestation_status") == "confirmed":
                return False
            return self.store.set_attestation(cid, "confirmed", tx_hash=case.get("attestation_tx") or tx)
        if name == "Held":
            fields: dict[str, Any] = {}
            if case.get("hold_id") is None and hold_id is not None:
                fields["hold_id"] = int(hold_id)
            if not case.get("deposit_tx"):
                fields["deposit_tx"] = tx
            if not case.get("hold_status"):
                fields["hold_status"] = "HELD"
            if status == "DECIDED" and case["verdict"] == "HOLD":
                fields["status"] = "HELD_ESCROWED"
            return self.store.update_case(cid, **fields) if fields else False
        if name in ("Released", "Refunded"):
            final = "RELEASED" if name == "Released" else "REFUNDED"
            fields = {}
            if status != final:
                fields["status"] = final
            if case.get("hold_status") != final:
                fields["hold_status"] = final
            if case.get("hold_id") is None and hold_id is not None:
                fields["hold_id"] = int(hold_id)
            if not case.get("action_tx"):
                fields["action_tx"] = tx
            return self.store.update_case(cid, **fields) if fields else False
        if name == "VerdictOverridden":
            if is_new:
                self.store.audit("chain", "VerdictOverridden", cid, {"tx_hash": tx, **inputs})
            if not case.get("override_tx"):
                return self.store.update_case(cid, override_tx=tx)
            return False
        return False


def build_router(get_services: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    @router.post("/webhooks/multibaas")
    async def multibaas_webhook(request: Request) -> JSONResponse:
        svc = get_services()
        body = await request.body()
        ts = request.headers.get("x-multibaas-timestamp", "")
        sig = request.headers.get("x-multibaas-signature", "")
        secret = svc.settings.mb_webhook_secret.get_secret_value()
        verify = svc.verify_webhook
        if not secret:
            log.error("webhook rejected: MB_WEBHOOK_SECRET not set")
            return JSONResponse({"error": "unauthorized", "message": "webhook secret not configured"}, status_code=401)
        if verify is None:
            log.error("webhook rejected: signature verifier unavailable", extra={"error": svc.client_errors.get("multibaas")})
            return JSONResponse({"error": "unauthorized", "message": "signature verifier unavailable"}, status_code=401)
        try:
            valid = bool(ts and sig and verify(body, ts, sig, secret))
        except Exception:
            valid = False
        if not valid:
            log.warning("webhook rejected: bad signature")
            return JSONResponse({"error": "unauthorized", "message": "bad or missing webhook signature"}, status_code=401)
        try:
            payload = json.loads(body)
        except ValueError:
            return JSONResponse({"error": "invalid_request", "message": "body is not JSON"}, status_code=400)
        items = payload if isinstance(payload, list) else [payload]
        handled = 0
        for item in items:
            if not isinstance(item, dict) or item.get("event") != "event.emitted":
                continue
            try:
                ev = svc.parse_event(item.get("data") or {})
            except Exception as exc:
                log.warning("webhook item not parsed", extra={"error": f"{type(exc).__name__}: {exc}"})
                continue
            if svc.handler.handle(ev, source="webhook") is not None:
                handled += 1
        return JSONResponse({"ok": True})

    return router


class FallbackPoller:
    """If a transaction we sent (or were told about) has no chain event 60 s later,
    fetch its events from MultiBaas by tx hash, every 30 s, for up to an hour."""

    def __init__(self, *, mb: Any, store: Any, handler: ChainEventHandler, tracked: dict[str, float]):
        self.mb = mb
        self.store = store
        self.handler = handler
        self.tracked = tracked  # tx hash -> first seen (shared with the attestor)
        self.task: asyncio.Task | None = None

    def start(self) -> None:
        if self.task is None and self.mb is not None and getattr(self.mb, "configured", False):
            self.task = asyncio.create_task(self._run(), name="fallback-poller")

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
            self.task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(POLL_EVERY_S)
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("fallback poll failed")

    async def poll_once(self, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        due = []
        for tx, seen in list(self.tracked.items()):
            if now - seen > POLL_GIVE_UP_S or self.store.has_chain_event(tx):
                self.tracked.pop(tx, None)
            elif now - seen >= POLL_AFTER_S:
                due.append(tx)
        found = 0
        for tx in due[:POLL_MAX_TXS]:
            try:
                events = await self.mb.list_events(tx_hash=tx, limit=20)
            except Exception as exc:
                log.warning("fallback poll: list_events failed", extra={"tx_hash": tx, "error": str(exc)[:200]})
                continue
            for ev in events or []:
                if ev.get("name") in KNOWN_EVENTS and self.handler.handle(ev, source="poller") is not None:
                    found += 1
        return found
