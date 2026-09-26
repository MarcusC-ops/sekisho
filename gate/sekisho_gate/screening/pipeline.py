"""Screening pipeline (PRD 9.2): parallel checks, policy, report, persistence, then the
background work (attestation, analyst note, post-HOLD Deep Scan).

- Checks run in parallel with per-check timeouts inside an overall 8 s budget.
- A failed or timed-out check is recorded with status "error", never dropped.
- Fail closed: a failed Quick Scan (or one with an unexpected shape) is at least HOLD.
- Identical complete requests under unchanged policy/override/config within 10 s get the
  same case, including requests that arrive while the first is still screening.
- The verdict returns immediately; nothing in the background can change it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Awaitable, Callable

from ..checks import (
    CHECK_ORDER,
    DEEP_SCAN,
    EVIDENCE_IDS,
    IMPERSONATION,
    ORACLE,
    OVERALL_BUDGET_S,
    QUICK_SCAN,
    TIMEOUTS_S,
    TOKEN,
    TRACE,
)
from ..logs import case_id_var, get_logger
from ..models import ScreenRequest
from ..policy.engine import quick_scan_data
from ..report import build_report, check_entry, ordered_checks, seal
from ..store import dumps
from ..util import amount_to_usd, case_id_b32, iso, new_case_id, token_scan_target, validate_payment_asset
from ..views import case_detail_view, decision_view
from .types import CheckOutcome

log = get_logger("sekisho.pipeline")

IDEMPOTENCY_WINDOW_S = 10.0
FAULT_INTERCEPTA_TIMEOUT = "intercepta_timeout"


def idempotency_key(req: ScreenRequest, context: dict[str, Any] | None = None) -> str:
    material = json.dumps([req.model_dump(mode="json"), context], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode()).hexdigest()


def check_view(o: CheckOutcome) -> dict[str, Any]:
    return {
        "name": o.name,
        "status": o.status,
        "live": o.live,
        "latency_ms": o.latency_ms,
        "summary": o.summary,
        "evidence_id": EVIDENCE_IDS.get(o.name),
        "error": o.error,
    }


def _default_summary(o: CheckOutcome) -> str:
    if o.status != "ok" or not isinstance(o.data, dict):
        return o.summary or (o.error or o.status)
    d = o.data
    if o.name in (QUICK_SCAN, DEEP_SCAN):
        return f"toxicScore {d.get('toxicScore')}, {len(d.get('traits') or [])} traits"
    if o.name == ORACLE:
        hits = [k for k, v in d.items() if v is True]
        return f"sanctioned on {', '.join(hits)}" if hits else "not sanctioned"
    if o.name == TRACE:
        return f"taint {d.get('taint_pct', 0)}%, {len(d.get('hop1') or [])} funders"
    if o.name == IMPERSONATION:
        return "address poisoned" if d.get("isAddressPoisoned") else "not poisoned"
    if o.name == TOKEN:
        return f"action {d.get('action')}, risk {d.get('riskLevel')}"
    return ""


class _InjectedTimeout(TimeoutError):
    pass


class ScreeningPipeline:
    def __init__(
        self,
        *,
        settings: Any,
        policy: Any,
        store: Any,
        notifier: Any,
        intercepta: Any,
        oracle: Any,
        tracer: Any,
        attestor: Any,
        analyst: Any,
        client_errors: dict[str, str] | None = None,
    ):
        self.settings = settings
        self.policy = policy
        self.store = store
        self.notifier = notifier
        self.intercepta = intercepta
        self.oracle = oracle
        self.tracer = tracer
        self.attestor = attestor
        self.analyst = analyst
        self.client_errors = client_errors or {}  # why a client is missing (import error)
        self._inflight: dict[str, asyncio.Task] = {}
        self._background: set[asyncio.Task] = set()

    @property
    def fault(self) -> str:
        return (self.settings.fault_inject or "").strip().lower()

    # ---------- entry point ----------

    def _request_key(self, req: ScreenRequest) -> str:
        override = self.store.active_override(req.counterparty)
        return idempotency_key(req, {
            "policy_id": self.policy.id,
            "override": override.as_dict() if override else None,
            "fault": self.fault,
            "screen_token": self.settings.screen_token,
            "screen_impersonation": self.settings.screen_impersonation,
            "always_live_direct": self.settings.always_live_direct,
            "usdc_address": self.settings.usdc_address,
        })

    async def screen(self, req: ScreenRequest) -> dict[str, Any]:
        validate_payment_asset(req.payment_chain_id, req.asset, self.settings.usdc_address)
        key = self._request_key(req)
        existing = self.store.idempotent_case_id(key, IDEMPOTENCY_WINDOW_S)
        if existing:
            row = self.store.get_case(existing)
            if row is not None:
                log.info("idempotent replay", extra={"case_id": existing})
                return decision_view(row, self.settings.explorer_url)
        task = self._inflight.get(key)
        if task is None:
            # Its own task: a client that disconnects mid-screening cannot cancel a
            # decision that is being made and recorded.
            task = asyncio.create_task(self._screen_new(req, key))
            self._inflight[key] = task
            task.add_done_callback(lambda t: self._inflight.pop(key, None) if self._inflight.get(key) is t else None)
        else:
            log.info("joined an in-flight identical request")
        return await asyncio.shield(task)

    # ---------- checks ----------

    async def _guarded(
        self, name: str, factory: Callable[[], Awaitable[CheckOutcome]], timeout_s: float
    ) -> CheckOutcome:
        t0 = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - t0) * 1000)

        try:
            out = await asyncio.wait_for(factory(), timeout_s)
        except _InjectedTimeout as exc:
            return CheckOutcome(name=name, status="error", latency_ms=elapsed(), summary="timeout", error=str(exc))
        except (asyncio.TimeoutError, TimeoutError):
            ms = int(timeout_s * 1000)
            return CheckOutcome(
                name=name, status="error", latency_ms=elapsed(), summary="timeout", error=f"timeout after {ms} ms"
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("check raised", extra={"check": name, "error": f"{type(exc).__name__}: {exc}"})
            return CheckOutcome(
                name=name, status="error", latency_ms=elapsed(), summary="error",
                error=f"{type(exc).__name__}: {exc}"[:500],
            )
        if not isinstance(out, CheckOutcome):
            return CheckOutcome(
                name=name, status="error", latency_ms=elapsed(), summary="error",
                error=f"client returned {type(out).__name__}, not CheckOutcome",
            )
        updates: dict[str, Any] = {}
        if out.name != name:
            log.warning("check name mismatch", extra={"expected": name, "got": out.name})
            updates["name"] = name
        if out.latency_ms is None:
            updates["latency_ms"] = elapsed()
        if updates:
            out = out.model_copy(update=updates)
        return self._normalise(out)

    def _normalise(self, o: CheckOutcome) -> CheckOutcome:
        # Anything unexpected in a Quick Scan counts as a failed scan (fail closed).
        if o.name in (QUICK_SCAN, DEEP_SCAN) and o.status == "ok" and quick_scan_data(o) is None:
            return o.model_copy(
                update={
                    "status": "error",
                    "summary": "unexpected response",
                    "error": "unexpected response shape (need numeric toxicScore and a traits list)",
                }
            )
        if o.status == "error" and not o.error:
            o = o.model_copy(update={"error": o.summary or "check failed"})
        if not o.summary:
            o = o.model_copy(update={"summary": _default_summary(o)})
        return o

    def _missing(self, name: str, client: str) -> CheckOutcome:
        why = self.client_errors.get(client, "client not available")
        return CheckOutcome(name=name, status="error", latency_ms=0, summary="unavailable", error=f"{client} client unavailable: {why}")

    @staticmethod
    def _skipped(name: str, why: str) -> CheckOutcome:
        return CheckOutcome(name=name, status="skipped", latency_ms=0, summary=why)

    async def _fault_timeout(self) -> CheckOutcome:
        timeout = TIMEOUTS_S[QUICK_SCAN]
        await asyncio.sleep(max(0.0, timeout - 0.05))
        raise _InjectedTimeout(
            f"timeout after {int(timeout * 1000)} ms (fault injected: FAULT_INJECT={FAULT_INTERCEPTA_TIMEOUT})"
        )

    async def run_checks(self, req: ScreenRequest) -> dict[str, CheckOutcome]:
        addr = req.counterparty
        s = self.settings
        factories: dict[str, Callable[[], Awaitable[CheckOutcome]]] = {}
        fixed: dict[str, CheckOutcome] = {}

        if self.fault == FAULT_INTERCEPTA_TIMEOUT:
            factories[QUICK_SCAN] = self._fault_timeout
        elif self.intercepta is None:
            fixed[QUICK_SCAN] = self._missing(QUICK_SCAN, "intercepta")
        else:
            factories[QUICK_SCAN] = lambda: self.intercepta.quick_scan(addr, live=bool(s.always_live_direct))

        if self.oracle is None:
            fixed[ORACLE] = self._missing(ORACLE, "sanctions")
        else:
            factories[ORACLE] = lambda: self.oracle.check(addr)

        if self.tracer is None:
            fixed[TRACE] = self._missing(TRACE, "tracer")
        else:
            factories[TRACE] = lambda: self.tracer.trace(addr)

        if not s.screen_impersonation:
            fixed[IMPERSONATION] = self._skipped(IMPERSONATION, "disabled by config")
        elif self.intercepta is None:
            fixed[IMPERSONATION] = self._missing(IMPERSONATION, "intercepta")
        else:
            factories[IMPERSONATION] = lambda: self.intercepta.impersonation(addr)

        target = token_scan_target(req.payment_chain_id, req.asset)
        if not s.screen_token:
            fixed[TOKEN] = self._skipped(TOKEN, "disabled by config")
        elif target is None:
            fixed[TOKEN] = self._skipped(TOKEN, "no mainnet equivalent for this payment asset")
        elif self.intercepta is None:
            fixed[TOKEN] = self._missing(TOKEN, "intercepta")
        else:
            chain_id, token = target
            factories[TOKEN] = lambda: self.intercepta.token_scan(token, chain_id)

        tasks = {
            name: asyncio.create_task(self._guarded(name, f, TIMEOUTS_S[name]), name=f"check-{name}")
            for name, f in factories.items()
        }
        results = dict(fixed)
        if tasks:
            done, pending = await asyncio.wait(tasks.values(), timeout=OVERALL_BUDGET_S)
            for name, task in tasks.items():
                if task in done:
                    results[name] = task.result()
                else:
                    task.cancel()
                    results[name] = CheckOutcome(
                        name=name, status="error", latency_ms=int(OVERALL_BUDGET_S * 1000), summary="timeout",
                        error=f"overall {OVERALL_BUDGET_S:g} s screening budget exceeded",
                    )
        return {name: results[name] for name in CHECK_ORDER if name in results}

    # ---------- evidence ----------

    def _evidence(self, outcomes: dict[str, CheckOutcome]) -> dict[str, Any]:
        def ok(name: str) -> dict[str, Any] | None:
            o = outcomes.get(name)
            return o.data if o is not None and o.status == "ok" and isinstance(o.data, dict) else None

        quick = None
        qs = outcomes.get(QUICK_SCAN)
        if qs is not None and quick_scan_data(qs) is not None:
            raw = qs.raw if isinstance(qs.raw, dict) else {}
            quick = {**raw, "toxicScore": qs.data.get("toxicScore"), "traits": self.policy.classified_traits(qs.data.get("traits"))}
        oracle = outcomes.get(ORACLE)
        return {
            "quick_scan": quick,
            "oracle": oracle.data if oracle is not None and isinstance(oracle.data, dict) else None,
            "impersonation": ok(IMPERSONATION),
            "token_scan": ok(TOKEN),
            "deep_scan": None,
        }

    # ---------- a new case ----------

    async def _screen_new(self, req: ScreenRequest, key: str) -> dict[str, Any]:
        received_ts = time.time()
        t0 = time.perf_counter()
        case_id = new_case_id()
        b32 = case_id_b32(case_id)
        token = case_id_var.set(case_id)
        try:
            s = self.settings
            amount_usd = amount_to_usd(req.amount, req.payment_chain_id, req.asset, s.usdc_address)
            outcomes = await self.run_checks(req)
            # Officer state may change while upstream calls are pending.
            override = self.store.active_override(req.counterparty)
            has_prior = self.store.has_prior_allow_or_paid(req.counterparty)
            key = self._request_key(req)
            decision = self.policy.evaluate(
                outcomes,
                amount_usd=amount_usd,
                direction=req.direction,
                override=override,
                has_prior_allow=has_prior,
            )
            decided_at = iso()
            latency_ms = int((time.perf_counter() - t0) * 1000)
            trace_outcome = outcomes.get(TRACE)
            trace = trace_outcome.data if trace_outcome is not None and trace_outcome.status == "ok" else None
            request_dict = req.model_dump(mode="json")
            report = build_report(
                case_id=case_id,
                case_id_b32=b32,
                request=request_dict,
                amount_usd=amount_usd,
                received_at=iso(received_ts),
                decided_at=decided_at,
                checks=outcomes.values(),
                trace=trace,
                policy=self.policy.ref(),
                decision=decision,
                history={"prior_allow_or_paid": has_prior},
                fault_inject=self.fault or None,
            )
            report_bytes, rhash = seal(report)
            status = "REFUSED" if decision.verdict == "BLOCK" else "DECIDED"
            ordered = ordered_checks(outcomes.values())
            decision_json = {
                "case_id": case_id,
                "case_id_b32": b32,
                "verdict": decision.verdict,
                "risk_score": decision.risk_score,
                "headline": decision.headline,
                "direction": req.direction,
                "counterparty": req.counterparty,
                "amount": req.amount,
                "amount_usd": amount_usd,
                "asset": req.asset,
                "payment_chain_id": req.payment_chain_id,
                "reasons": decision.reasons,
                "checks": [check_view(o) for o in ordered],
                "trace": trace,
                "policy": {"id": self.policy.id, "version": self.policy.version, "triggered_rules": decision.triggered_rules},
                "report_hash": rhash,
                "decided_at": decided_at,
                "latency_ms": latency_ms,
            }
            row = {
                "case_id": case_id,
                "case_id_b32": b32,
                "created_at": iso(received_ts),
                "created_ts": received_ts,
                "direction": req.direction,
                "counterparty": req.counterparty,
                "amount": req.amount,
                "amount_usd": amount_usd,
                "asset": req.asset,
                "payment_chain_id": req.payment_chain_id,
                "source": req.source,
                "agent_id": req.agent_id,
                "purpose": req.purpose,
                "resource": req.resource,
                "untrusted_context": req.untrusted_context,
                "verdict": decision.verdict,
                "risk_score": decision.risk_score,
                "status": status,
                "report_hash": rhash,
                "policy_id": self.policy.id,
                "decision_json": dumps(decision_json),
                "evidence_json": dumps(self._evidence(outcomes)),
                "attestation_status": "queued",
                "latency_ms": latency_ms,
                "decided_at": decided_at,
                "updated_at": decided_at,
            }
            check_rows = [check_entry(o) for o in ordered]
            self.store.insert_case(row, check_rows, rhash, report_bytes, key, received_ts)
            self.store.audit(
                "gate", "screened", case_id,
                {"verdict": decision.verdict, "risk_score": decision.risk_score, "report_hash": rhash},
            )
            view = decision_view(self.store.get_case(case_id), s.explorer_url)
            log.info(
                "screened",
                extra={
                    "verdict": decision.verdict,
                    "risk_score": decision.risk_score,
                    "rules": decision.triggered_rules,
                    "latency_ms": latency_ms,
                    "direction": req.direction,
                    "counterparty": req.counterparty,
                },
            )
            self.notifier.case_created(view)
            # Background work: none of it can change the verdict or the report hash.
            if self.attestor is not None:
                self.attestor.enqueue_screening(case_id)
            self._spawn(self._annotate(case_id))
            if decision.verdict == "HOLD":
                self._spawn(self._deep_scan(case_id, req.counterparty))
            return view
        finally:
            case_id_var.reset(token)

    # ---------- background ----------

    def _spawn(self, coro: Awaitable[Any]) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

    async def drain(self, timeout_s: float = 10.0) -> None:
        """Wait for background analyst / deep-scan tasks (tests, shutdown)."""
        if self._background:
            await asyncio.wait(set(self._background), timeout=timeout_s)

    async def _annotate(self, case_id: str) -> None:
        try:
            row = self.store.get_case(case_id)
            detail = case_detail_view(row, [], self.settings.explorer_url, validate=False)
            note = await self.analyst.note(detail)
            self.store.update_case(case_id, analyst_json=dumps(note))
            self.notifier.case_updated(case_id)
            log.info("analyst note stored", extra={"provider": note.get("provider"), "fallback": note.get("fallback")})
        except Exception:
            log.exception("analyst task failed")

    async def _deep_scan(self, case_id: str, address: str) -> None:
        """P1: enrich a HOLD for the officer. Not part of the hashed report."""
        try:
            if self.fault == FAULT_INTERCEPTA_TIMEOUT:
                out = self._skipped(DEEP_SCAN, "skipped: Intercepta fault injection active")
            elif self.intercepta is None:
                out = self._missing(DEEP_SCAN, "intercepta")
            else:
                out = await self._guarded(DEEP_SCAN, lambda: self.intercepta.deep_scan(address), TIMEOUTS_S[DEEP_SCAN])
            data = None
            if quick_scan_data(out) is not None:
                raw = out.raw if isinstance(out.raw, dict) else {}
                data = {**raw, "toxicScore": out.data.get("toxicScore"), "traits": self.policy.classified_traits(out.data.get("traits"))}
            self.store.add_check(case_id, check_entry(out))
            self.store.update_case(case_id, deep_scan_json=dumps({"check": check_view(out), "data": data}))
            self.notifier.case_updated(case_id)
            log.info("deep scan stored", extra={"status": out.status})
        except Exception:
            log.exception("deep scan task failed")
