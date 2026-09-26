"""The gate's service container: builds every client from the settings, starts and stops
the background workers, and answers /healthz and /v1/treasury.

There is no mock mode: a client that cannot be built (missing module, bad config) is
None, and every check that needs it is recorded as an error (fail closed).
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

import httpx

from .analyst.llm import Analyst, LLMClient
from .chain.attest import Attestor, describe_error, signer_from
from .logs import get_logger
from .policy import Policy
from .screening.pipeline import ScreeningPipeline
from .sse import Broker
from .store import Store
from .util import checksum_or_none, iso
from .views import CaseNotifier
from .webhooks import ChainEventHandler, FallbackPoller

log = get_logger("sekisho.services")

TREASURY_CACHE_S = 60.0
MB_HEALTH_CACHE_S = 30.0
RPC_HEALTH_CACHE_S = 15.0
ORACLE_RETEST_S = 60.0
_UNSET = object()


def _build(name: str, errors: dict[str, str], factory: Callable[[], Any]) -> Any:
    try:
        return factory()
    except Exception as exc:  # the gate still starts; checks that need it fail closed
        errors[name] = f"{type(exc).__name__}: {exc}"
        log.error("client unavailable", extra={"client": name, "error": errors[name]})
        return None


def _usdc_usd(atomic: str | None) -> float | None:
    if atomic is None:
        return None
    return round(int(atomic) / 1_000_000, 6)


def _atomic(value: Any) -> str:
    """MultiBaas ints arrive as numbers or decimal strings (hex tolerated)."""
    if isinstance(value, str) and value.lower().startswith("0x"):
        return str(int(value, 16))
    try:
        return str(int(Decimal(str(value))))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not an integer: {value!r}") from exc


def payee_rows(rows: Any) -> list[dict[str, Any]]:
    """Event Query rows -> [{payee, total, total_usd}]. Keys come back lowercased."""
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        low = {str(k).lower(): v for k, v in row.items()}
        total = _atomic(low.get("total"))
        payee = checksum_or_none(low.get("payee")) or str(low.get("payee"))
        out.append({"payee": payee, "total": total, "total_usd": _usdc_usd(total)})
    return out


class Services:
    def __init__(
        self,
        settings: Any,
        *,
        store: Any = None,
        intercepta: Any = _UNSET,
        oracle: Any = _UNSET,
        tracer: Any = _UNSET,
        mb: Any = _UNSET,
        llm: Any = _UNSET,
        verify_webhook: Any = _UNSET,
        parse_event: Any = _UNSET,
        screener: Any = None,
        officer: Any = None,
        http: httpx.AsyncClient | None = None,
    ):
        self.settings = settings
        self.client_errors: dict[str, str] = {}
        self.policy = Policy(settings.policy_path)
        self.store = store if store is not None else Store(settings.db_path)
        self.broker = Broker()
        self.http = http or httpx.AsyncClient(timeout=5.0)

        errs = self.client_errors

        def make_intercepta() -> Any:
            from .screening.intercepta import InterceptaClient

            return InterceptaClient(settings)

        def make_oracle() -> Any:
            from .screening.sanctions import SanctionsOracle

            return SanctionsOracle(settings)

        def make_mb() -> Any:
            from .chain.multibaas import MultiBaasClient

            return MultiBaasClient(settings)

        self.intercepta = _build("intercepta", errs, make_intercepta) if intercepta is _UNSET else intercepta
        self.oracle = _build("sanctions", errs, make_oracle) if oracle is _UNSET else oracle

        def make_tracer() -> Any:
            from .screening.tracer import Tracer

            if self.oracle is None or self.intercepta is None:
                raise RuntimeError("needs the sanctions oracle and the Intercepta client")
            return Tracer(settings, self.oracle, self.intercepta, self.policy.parsed)

        self.tracer = _build("tracer", errs, make_tracer) if tracer is _UNSET else tracer
        self.mb = _build("multibaas", errs, make_mb) if mb is _UNSET else mb

        if verify_webhook is _UNSET or parse_event is _UNSET:
            try:
                from .chain.multibaas import parse_event as _parse
                from .chain.multibaas import verify_webhook_signature as _verify
            except Exception as exc:
                errs.setdefault("multibaas", f"{type(exc).__name__}: {exc}")
                _verify, _parse = None, None
            self.verify_webhook = _verify if verify_webhook is _UNSET else verify_webhook
            self.parse_event = _parse if parse_event is _UNSET else parse_event
        else:
            self.verify_webhook, self.parse_event = verify_webhook, parse_event

        self.llm = LLMClient(settings) if llm is _UNSET else llm
        self.analyst = Analyst(self.llm, self.policy)
        self.notifier = CaseNotifier(self.store, self.broker, settings.explorer_url, self.quota)
        self.attestor = Attestor(
            settings=settings, policy=self.policy, store=self.store, mb=self.mb,
            notifier=self.notifier, screener=screener, officer=officer,
        )
        self.pipeline = ScreeningPipeline(
            settings=settings, policy=self.policy, store=self.store, notifier=self.notifier,
            intercepta=self.intercepta, oracle=self.oracle, tracer=self.tracer,
            attestor=self.attestor, analyst=self.analyst, client_errors=errs,
        )
        self.handler = ChainEventHandler(store=self.store, notifier=self.notifier, explorer_url=settings.explorer_url)
        self.poller = FallbackPoller(mb=self.mb, store=self.store, handler=self.handler, tracked=self.attestor.tracked_txs)

        self._oracle_test: tuple[bool, str] | None = None
        self._oracle_test_at = 0.0
        self._mb_health: tuple[float, tuple[bool, str]] | None = None
        self._rpc_health: tuple[float, tuple[bool, str]] | None = None
        self._treasury_cache: tuple[float, dict[str, Any]] | None = None
        self._startup: list[asyncio.Task] = []

    # ---------- lifecycle ----------

    async def start(self) -> None:
        self.attestor.start()
        for case_id in self.store.queued_attestations():  # left in the queue by a restart
            self.attestor.enqueue_screening(case_id)
        for tx in self.store.pending_tx_hashes():
            self.attestor.track_tx(tx)
        self.poller.start()
        self._startup.append(asyncio.create_task(self.run_oracle_self_test(), name="oracle-self-test"))
        log.info(
            "gate started",
            extra={
                "policy_id": self.policy.id,
                "demo_mode": self.settings.demo_mode,
                "clients_unavailable": sorted(self.client_errors),
                "fault_inject": self.settings.fault_inject or None,
            },
        )

    async def stop(self) -> None:
        for t in self._startup:
            t.cancel()
        await self.poller.stop()
        await self.pipeline.drain(timeout_s=2.0)
        await self.attestor.stop()
        for client in (self.intercepta, self.oracle, self.tracer, self.mb, self.llm):
            closer = getattr(client, "aclose", None)
            if closer is not None:
                try:
                    await closer()
                except Exception:
                    pass
        await self.http.aclose()
        self.store.close()

    # ---------- quota ----------

    def quota(self) -> dict[str, Any] | None:
        return self.intercepta.quota_status() if self.intercepta is not None else None

    # ---------- health ----------

    async def run_oracle_self_test(self) -> tuple[bool, str]:
        if self.oracle is None:
            result = (False, f"sanctions client unavailable: {self.client_errors.get('sanctions', '?')}")
        else:
            try:
                result = await asyncio.wait_for(self.oracle.self_test(), 6.0)
            except Exception as exc:
                result = (False, f"self-test failed: {type(exc).__name__}: {exc}")
        self._oracle_test, self._oracle_test_at = result, time.time()
        (log.info if result[0] else log.error)("oracle self-test", extra={"ok": result[0], "detail": result[1]})
        return result

    async def _oracle_health(self) -> tuple[bool, str]:
        if self._oracle_test is None:
            return False, "self-test pending"
        if not self._oracle_test[0] and time.time() - self._oracle_test_at > ORACLE_RETEST_S:
            return await self.run_oracle_self_test()
        return self._oracle_test

    async def _mb_health_check(self) -> tuple[bool, str]:
        if self.mb is None:
            return False, f"client unavailable: {self.client_errors.get('multibaas', '?')}"
        if not getattr(self.mb, "configured", False):
            return False, "not configured (MB_URL / MB_ADMIN_API_KEY unset)"
        now = time.time()
        if self._mb_health and now - self._mb_health[0] < MB_HEALTH_CACHE_S:
            return self._mb_health[1]
        try:
            result = await asyncio.wait_for(self.mb.health(), 5.0)
        except Exception as exc:
            result = (False, f"unreachable: {type(exc).__name__}: {exc}")
        self._mb_health = (now, result)
        return result

    async def _rpc_health_check(self) -> tuple[bool, str]:
        now = time.time()
        if self._rpc_health and now - self._rpc_health[0] < RPC_HEALTH_CACHE_S:
            return self._rpc_health[1]
        url = self.settings.contracts_rpc_url
        try:
            r = await self.http.post(
                url,
                json=[
                    {"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []},
                    {"jsonrpc": "2.0", "id": 2, "method": "eth_blockNumber", "params": []},
                ],
                timeout=4.0,
            )
            r.raise_for_status()
            by_id = {item.get("id"): item.get("result") for item in r.json()}
            chain, block = int(by_id[1], 16), int(by_id[2], 16)
            ok = chain == int(self.settings.chain_id)
            detail = f"chain {chain}, block {block}" + ("" if ok else f" (expected chain {self.settings.chain_id})")
            result = (ok, detail)
        except Exception as exc:
            result = (False, f"{url} unreachable: {type(exc).__name__}: {str(exc)[:120]}")
        self._rpc_health = (now, result)
        return result

    def _intercepta_health(self) -> tuple[bool, str]:
        if self.intercepta is None:
            return False, f"client unavailable: {self.client_errors.get('intercepta', '?')}"
        try:
            ok, detail = self.intercepta.key_status()
            if "used" not in detail:
                q = self.intercepta.quota_status()
                detail = f"{detail}, {q.get('used')}/{q.get('quota')} used"
        except Exception as exc:
            ok, detail = False, f"status error: {type(exc).__name__}: {exc}"
        if self.settings.fault_inject:
            ok, detail = False, f"{detail}; FAULT_INJECT={self.settings.fault_inject} active"
        return ok, detail

    async def health(self) -> dict[str, Any]:
        oracle, mb, rpc = await asyncio.gather(
            self._oracle_health(), self._mb_health_check(), self._rpc_health_check()
        )
        checks = {
            "intercepta": self._intercepta_health(),
            "oracle_self_test": oracle,
            "multibaas": mb,
            "contracts_rpc": rpc,
            "llm": self.llm.status() if self.llm is not None else (True, "LLM disabled: template notes"),
        }
        return {
            "status": "ok" if all(ok for ok, _ in checks.values()) else "degraded",
            "demo_mode": bool(self.settings.demo_mode),
            "policy": {"id": self.policy.id, "version": self.policy.version},
            "checks": {k: {"ok": bool(ok), "detail": str(detail)} for k, (ok, detail) in checks.items()},
        }

    # ---------- treasury (P1) ----------

    async def _treasury_multibaas(self) -> dict[str, Any]:
        s = self.settings
        out: dict[str, Any] = {
            "buyer_address": None, "buyer_usdc": None, "escrow_address": None,
            "escrow_total_held": None, "exposure_by_payee": None, "released_by_payee": None,
        }
        errors: list[str] = []
        buyer = signer_from(s.buyer_agent_pk.get_secret_value())
        if buyer is not None:
            out["buyer_address"] = buyer.address
        else:
            errors.append("buyer_address: BUYER_AGENT_PK not set")
        if self.mb is None or not getattr(self.mb, "configured", False):
            errors.append("MultiBaas not configured (MB_URL / MB_ADMIN_API_KEY unset)")
            return {**out, "errors": errors}

        async def read(field: str, coro_fn: Callable[[], Any], convert: Callable[[Any], Any]) -> None:
            try:
                out[field] = convert(await asyncio.wait_for(coro_fn(), 8.0))
            except Exception as exc:
                errors.append(f"{field}: {describe_error(exc)}")

        jobs = [
            read("escrow_address", lambda: self.mb.address_of(s.escrow_alias), lambda v: checksum_or_none(v) or v),
            read("escrow_total_held", lambda: self.mb.call_read(s.escrow_alias, s.escrow_label, "totalHeld", []), _atomic),
            read("exposure_by_payee", lambda: self.mb.query_results("exposure_by_payee"), payee_rows),
            read("released_by_payee", lambda: self.mb.query_results("released_by_payee"), payee_rows),
        ]
        if buyer is not None:
            jobs.append(
                read("buyer_usdc", lambda: self.mb.call_read(s.usdc_alias, s.usdc_label, "balanceOf", [buyer.address]), _atomic)
            )
        await asyncio.gather(*jobs)
        return {**out, "errors": errors}

    def _treasury_store(self) -> dict[str, Any]:
        rows = self.store.active_cases()
        paid_x402 = sum(float(r["amount_usd"] or 0) for r in rows if r["status"] == "PAID" and r["source"] == "x402")
        blocked = sum(float(r["amount_usd"] or 0) for r in rows if r["verdict"] == "BLOCK")
        book: dict[str, dict[str, Any]] = {}
        for r in rows:  # oldest first, so the last write wins for "latest"
            e = book.setdefault(
                r["counterparty"],
                {"counterparty": r["counterparty"], "total_paid_usd": 0.0, "total_held_usd": 0.0, "cases": 0},
            )
            e["latest_verdict"], e["last_screened_at"] = r["verdict"], r["created_at"]
            e["cases"] += 1
            if r["status"] == "PAID":
                e["total_paid_usd"] += float(r["amount_usd"] or 0)
            if r["status"] == "HELD_ESCROWED":
                e["total_held_usd"] += float(r["amount_usd"] or 0)
        entries = sorted(book.values(), key=lambda e: e["last_screened_at"], reverse=True)
        for e in entries:
            e["total_paid_usd"] = round(e["total_paid_usd"], 6)
            e["total_held_usd"] = round(e["total_held_usd"], 6)
        return {
            "paid_via_x402_usd": round(paid_x402, 6),
            "value_blocked_usd": round(blocked, 6),
            "counterparty_book": entries,
        }

    async def treasury(self) -> dict[str, Any]:
        now = time.time()
        if self._treasury_cache is None or now - self._treasury_cache[0] >= TREASURY_CACHE_S:
            self._treasury_cache = (now, await self._treasury_multibaas())
        cached_at, mbpart = self._treasury_cache
        mbpart = dict(mbpart)
        errors = list(mbpart.pop("errors", []))
        return {
            **mbpart,
            "buyer_usdc_usd": _usdc_usd(mbpart.get("buyer_usdc")),
            "escrow_total_held_usd": _usdc_usd(mbpart.get("escrow_total_held")),
            **self._treasury_store(),
            "source": "multibaas",
            "cached_at": iso(cached_at),
            "errors": errors,
        }
