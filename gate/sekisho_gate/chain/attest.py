"""Onchain writes through MultiBaas (PRD 9.8, 9.11 decision flow).

One asyncio.Queue and one worker per signer key (screener, officer): a lane runs one
job at a time and waits for the receipt before the next, so two transactions from the
same key are never in flight together (single nonce lane).

- Attestations: `recordScreening(subject, verdict, riskScore, ttlSeconds, reportHash,
  policyId, caseId)` on compliance_registry, signed by GATE_SCREENER_PK, TTL from the
  policy. Status queued -> submitted -> confirmed | failed; the verdict is never delayed.
- Officer decisions (POST /v1/cases/{id}/decision): overrideVerdict, wait, then
  release/refund on the escrow (outbound), or the override only (inbound).
  Contract reverts become 409 {"error": "<RevertName>"}.

The MultiBaas client comes from chain/multibaas.py; errors are read by duck typing
(`revert`, `selector`, `status`, `body`) so this module imports nothing from it.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Awaitable, Callable

from eth_account import Account

from ..errors import GateError, invalid_state, not_found
from ..logs import case_id_var, get_logger
from ..models import VERDICT_CODE
from ..util import note_hash

log = get_logger("sekisho.attest")

RECEIPT_TIMEOUT_S = 30.0

# 4-byte selectors of the contracts' custom errors (PRD 9.11 step 6, checked with keccak).
REVERT_SELECTORS = {
    "0x92a032ca": "NotCleared",
    "0x845eadf1": "NotHeld",
    "0xecbe11eb": "PayeeBlocked",
    "0x1f2a2005": "ZeroAmount",
    "0x1435e357": "NotPayer",
    "0x085de625": "TooEarly",
    "0xe2517d3f": "AccessControlUnauthorizedAccount",
    "0xfbcebe72": "InvalidVerdict",
    "0x15561365": "InvalidScore",
    "0x3dc68a66": "InvalidTtl",
}


def revert_name(exc: BaseException) -> str | None:
    """Decode a contract revert from a MultiBaas error (compose-time gas estimation)."""
    name = getattr(exc, "revert", None)
    if name:
        return str(name)
    selector = getattr(exc, "selector", None)
    if selector and str(selector).lower() in REVERT_SELECTORS:
        return REVERT_SELECTORS[str(selector).lower()]
    text = f"{getattr(exc, 'body', '') or ''} {exc}"
    low = text.lower()
    for sel, nm in REVERT_SELECTORS.items():
        if sel[2:] in low:
            return nm
    for nm in REVERT_SELECTORS.values():
        if re.search(rf"\b{nm}\b", text):
            return nm
    return None


def describe_error(exc: BaseException) -> str:
    status = getattr(exc, "status", None)
    body = str(getattr(exc, "body", "") or "")
    text = str(exc) or type(exc).__name__
    if status is not None:
        text = f"HTTP {status}: {text}"
    if body and body not in text:
        text = f"{text} ({body[:200]})"
    return text[:500]


def signer_from(pk: str) -> Any:
    return Account.from_key(pk) if pk else None


class SignerLane:
    """One queue, one worker: jobs for one key run strictly one after another."""

    def __init__(self, name: str):
        self.name = name
        self.queue: asyncio.Queue[tuple[Callable[[], Awaitable[Any]], asyncio.Future]] = asyncio.Queue()
        self.task: asyncio.Task | None = None
        self.active = 0  # jobs running right now (0 or 1)

    def start(self) -> None:
        if self.task is None:
            self.task = asyncio.create_task(self._run(), name=f"lane-{self.name}")

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
            self.task = None

    def submit(self, job: Callable[[], Awaitable[Any]]) -> asyncio.Future:
        fut = asyncio.get_running_loop().create_future()
        fut.add_done_callback(lambda f: f.cancelled() or f.exception())  # mark retrieved
        self.queue.put_nowait((job, fut))
        return fut

    async def _run(self) -> None:
        while True:
            job, fut = await self.queue.get()
            self.active += 1
            try:
                result = await job()
            except asyncio.CancelledError:
                if not fut.done():
                    fut.cancel()
                raise
            except BaseException as exc:  # noqa: BLE001 - delivered to the waiter
                if not fut.done():
                    fut.set_exception(exc)
            else:
                if not fut.done():
                    fut.set_result(result)
            finally:
                self.active -= 1
                self.queue.task_done()


class Attestor:
    def __init__(
        self,
        *,
        settings: Any,
        policy: Any,
        store: Any,
        mb: Any,
        notifier: Any,
        screener: Any = None,
        officer: Any = None,
    ):
        self.settings = settings
        self.policy = policy
        self.store = store
        self.mb = mb
        self.notifier = notifier
        self.screener = screener if screener is not None else signer_from(
            settings.gate_screener_pk.get_secret_value()
        )
        self.officer = officer if officer is not None else signer_from(settings.officer_pk.get_secret_value())
        self.screener_lane = SignerLane("screener")
        self.officer_lane = SignerLane("officer")
        self._deciding: set[str] = set()
        self.tracked_txs: dict[str, float] = {}  # tx hash -> first seen (fallback poller)

    # ---------- lifecycle ----------

    def start(self) -> None:
        self.screener_lane.start()
        self.officer_lane.start()

    async def stop(self) -> None:
        await self.screener_lane.stop()
        await self.officer_lane.stop()

    @property
    def mb_configured(self) -> bool:
        return self.mb is not None and bool(getattr(self.mb, "configured", False))

    def track_tx(self, tx_hash: str | None) -> None:
        if tx_hash:
            self.tracked_txs.setdefault(tx_hash, time.time())

    # ---------- attestations ----------

    def enqueue_screening(self, case_id: str) -> asyncio.Future:
        return self.screener_lane.submit(lambda: self._attest(case_id))

    def _fail(self, case_id: str, error: str) -> None:
        log.warning("attestation failed", extra={"error": error})
        self.store.set_attestation(case_id, "failed", error=error)
        self.notifier.case_updated(case_id)

    def _ttl(self, row: dict[str, Any]) -> int:
        """verdict_ttl_seconds from the policy. An ALLOW that only exists because of an
        officer clearance (rule 0) never outlives that clearance onchain."""
        ttl = self.policy.ttl_for(row["verdict"])
        if row["verdict"] == "ALLOW":
            override = self.store.active_override(row["counterparty"])
            if override is not None and override.verdict == "ALLOW":
                ttl = max(1, min(ttl, int(override.expires_at - time.time())))
        return ttl

    async def _attest(self, case_id: str) -> None:
        token = case_id_var.set(case_id)
        try:
            row = self.store.get_case(case_id)
            if row is None:
                return
            if not self.mb_configured:
                return self._fail(case_id, "MultiBaas not configured (MB_URL / MB_ADMIN_API_KEY unset); not attested onchain")
            if self.screener is None:
                return self._fail(case_id, "GATE_SCREENER_PK not set; not attested onchain")
            args = [
                row["counterparty"],
                VERDICT_CODE[row["verdict"]],
                str(int(row["risk_score"])),
                str(self._ttl(row)),
                row["report_hash"],
                row["policy_id"],
                row["case_id_b32"],
            ]
            s = self.settings
            try:
                tx = await self.mb.call_write(s.registry_alias, s.registry_label, "recordScreening", args, self.screener)
            except Exception as exc:
                name = revert_name(exc)
                return self._fail(
                    case_id,
                    f"recordScreening refused: {name}" if name else f"recordScreening failed: {describe_error(exc)}",
                )
            self.track_tx(tx)
            self.store.set_attestation(case_id, "submitted", tx_hash=tx)
            self.notifier.case_updated(case_id)
            log.info("attestation submitted", extra={"tx_hash": tx})
            try:
                receipt = await self.mb.wait_for_receipt(tx, RECEIPT_TIMEOUT_S)
            except Exception as exc:
                return self._fail(case_id, f"no receipt for {tx} within {RECEIPT_TIMEOUT_S:g} s: {describe_error(exc)}")
            if receipt and int(receipt.get("status", 0) or 0) == 1:
                self.store.set_attestation(case_id, "confirmed", tx_hash=tx)
                self.notifier.case_updated(case_id, metrics=True)
                log.info("attestation confirmed", extra={"tx_hash": tx, "block": receipt.get("blockNumber")})
            elif receipt is None:
                self._fail(case_id, f"no receipt for {tx} within {RECEIPT_TIMEOUT_S:g} s")
            else:
                self._fail(case_id, f"recordScreening transaction {tx} reverted onchain")
        except Exception as exc:  # never crash the lane
            log.exception("attestation job crashed")
            self._fail(case_id, f"attestation error: {type(exc).__name__}: {exc}")
        finally:
            case_id_var.reset(token)

    # ---------- officer decisions ----------

    def _check_state(self, row: dict[str, Any], action: str) -> None:
        direction, status, verdict = row["direction"], row["status"], row["verdict"]
        if verdict != "HOLD":
            raise invalid_state(f"only HOLD cases can be decided (case is {verdict}, {status})")
        if action == "release_unchecked" and direction != "outbound":
            raise invalid_state("release_unchecked needs an escrow hold (outbound cases only)")
        if direction == "outbound":
            if status != "HELD_ESCROWED" or row.get("hold_id") is None:
                raise invalid_state(
                    f"outbound HOLD case must be HELD_ESCROWED with a linked hold (status {status})"
                )
        elif status != "DECIDED":
            raise invalid_state(f"inbound HOLD case must be DECIDED (status {status})")

    async def decide(self, case_id: str, action: str, note: str) -> dict[str, Any]:
        row = self.store.get_case(case_id)
        if row is None:
            raise not_found(f"case {case_id}")
        if action == "release_unchecked" and not self.settings.demo_mode:
            raise GateError(403, "demo_mode_only", "release_unchecked is only available when DEMO_MODE=true")
        self._check_state(row, action)
        if case_id in self._deciding:
            raise invalid_state("a decision for this case is already in progress")
        if not self.mb_configured:
            raise GateError(502, "chain_error", "MultiBaas not configured (MB_URL / MB_ADMIN_API_KEY unset)")
        if self.officer is None:
            raise GateError(502, "chain_error", "OFFICER_PK not set")
        self._deciding.add(case_id)
        try:
            fut = self.officer_lane.submit(lambda: self._decide_job(case_id, action, note))
            return await asyncio.shield(fut)
        finally:
            self._deciding.discard(case_id)

    async def _write_and_wait(self, alias: str, label: str, method: str, args: list, what: str) -> str:
        try:
            tx = await self.mb.call_write(alias, label, method, args, self.officer)
        except Exception as exc:
            name = revert_name(exc)
            if name:
                raise GateError(409, name, f"{what} refused by the contract: {name}") from exc
            raise GateError(502, "chain_error", f"{what} failed: {describe_error(exc)}") from exc
        self.track_tx(tx)
        log.info("officer tx submitted", extra={"method": method, "tx_hash": tx})
        try:
            receipt = await self.mb.wait_for_receipt(tx, RECEIPT_TIMEOUT_S)
        except Exception as exc:
            raise GateError(502, "chain_error", f"{what}: no receipt for {tx}: {describe_error(exc)}") from exc
        if not receipt:
            raise GateError(502, "chain_error", f"{what}: no receipt for {tx} within {RECEIPT_TIMEOUT_S:g} s")
        if int(receipt.get("status", 0) or 0) != 1:
            raise GateError(502, "chain_error", f"{what}: transaction {tx} reverted onchain")
        return tx

    async def _decide_job(self, case_id: str, action: str, note: str) -> dict[str, Any]:
        token = case_id_var.set(case_id)
        try:
            row = self.store.get_case(case_id)
            self._check_state(row, action)  # re-check: state may have moved while queued
            s = self.settings
            subject, b32, direction = row["counterparty"], row["case_id_b32"], row["direction"]
            hold_id = row.get("hold_id")
            override_tx = action_tx = None
            hold_status = row.get("hold_status")
            self.store.audit("officer", f"decision.{action}", case_id, {"note": note})

            if action == "release_unchecked":
                action_tx = await self._write_and_wait(
                    s.escrow_alias, s.escrow_label, "release", [str(hold_id)],
                    f"release(holdId={hold_id}) without override",
                )
                status, hold_status = "RELEASED", "RELEASED"
            else:
                target = "ALLOW" if action == "release" else "BLOCK"
                ttl = self.policy.officer_clear_ttl_seconds if target == "ALLOW" else self.policy.ttl_for("BLOCK")
                override_tx = await self._write_and_wait(
                    s.registry_alias, s.registry_label, "overrideVerdict",
                    [subject, VERDICT_CODE[target], str(ttl), note_hash(note), b32],
                    f"overrideVerdict({target})",
                )
                self.store.put_override(subject, target, int(time.time()) + ttl, case_id, override_tx)
                self.store.update_case(case_id, override_tx=override_tx, officer_note=note)
                self.store.audit("officer", f"override.{target}", case_id, {"tx_hash": override_tx, "ttl_seconds": ttl})
                self.notifier.case_updated(case_id)
                if direction == "outbound":
                    method = "release" if action == "release" else "refund"
                    action_tx = await self._write_and_wait(
                        s.escrow_alias, s.escrow_label, method, [str(hold_id)], f"{method}(holdId={hold_id})"
                    )
                    status = hold_status = "RELEASED" if action == "release" else "REFUNDED"
                else:
                    status = "CLEARED" if action == "release" else "REJECTED"

            fields: dict[str, Any] = {"status": status, "officer_note": note}
            if action_tx:
                fields["action_tx"] = action_tx
            if hold_id is not None and hold_status:
                fields["hold_status"] = hold_status
            self.store.update_case(case_id, **fields)
            self.store.audit(
                "officer", f"decided.{status}", case_id, {"override_tx": override_tx, "action_tx": action_tx}
            )
            self.notifier.case_updated(case_id, metrics=True)
            log.info("officer decision done", extra={"action": action, "status": status})
            return {"override_tx": override_tx, "action_tx": action_tx, "status": status}
        except GateError as exc:
            self.store.audit("officer", "decision.failed", case_id, {"action": action, "error": exc.body()})
            self.notifier.case_updated(case_id)
            raise
        finally:
            case_id_var.reset(token)
