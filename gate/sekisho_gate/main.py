"""Sekisho gate: the FastAPI app (docs/api.md).

Run: .venv/bin/python -m uvicorn sekisho_gate.main:app --port 8000
"""

from __future__ import annotations

import re
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sse_starlette.sse import EventSourceResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import require_operator
from .chain.attest import signer_from
from .config import Settings, get_settings
from .errors import GateError, invalid_state, not_found
from .logs import get_logger, setup_logging
from .models import (
    AuditList,
    CaseDetail,
    CaseList,
    CaseStatus,
    DecisionRequest,
    DecisionResult,
    DemoResetResult,
    Direction,
    ErrorBody,
    Health,
    HoldAck,
    HoldReport,
    Metrics,
    PaymentAck,
    PaymentReport,
    PolicyInfo,
    Quota,
    ScreeningDecision,
    ScreenRequest,
    Treasury,
    Verdict,
)
from .receipts import verify_hold_receipt, verify_payment_receipt
from .services import Services
from .sse import KEEPALIVE_S, parse_last_event_id
from .util import validate_payment_asset
from .views import case_detail_view, chain_event_view, decision_view
from .webhooks import build_router

log = get_logger("sekisho.gate")

_HEX32 = re.compile(r"^0x[0-9a-fA-F]{64}$")
_CASE_PATH = re.compile(r"^/v1/cases/(cs_[0-9A-Za-z]+)")
_STATUS_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
                 405: "method_not_allowed", 409: "conflict", 413: "too_large", 429: "rate_limited"}


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path"))
        msg = str(err.get("msg", "invalid")).removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) or "invalid request"


class RequestLog:
    """Pure-ASGI request logger (safe with SSE streaming), one JSON line per request,
    with the case id when the request concerns a case."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        t0 = time.perf_counter()
        status: dict[str, int | None] = {"code": None}

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            m = _CASE_PATH.match(path)
            case_id = (scope.get("state") or {}).get("case_id") or (m.group(1) if m else None)
            if path != "/healthz" or (status["code"] or 500) >= 400:
                log.info(
                    "request",
                    extra={
                        "case_id": case_id,
                        "method": scope.get("method"),
                        "path": path,
                        "status": status["code"],
                        "duration_ms": int((time.perf_counter() - t0) * 1000),
                    },
                )


def create_app(
    settings: Settings | None = None, services: Services | None = None, *, configure_logging: bool = True
) -> FastAPI:
    settings = settings or get_settings()
    if configure_logging:
        setup_logging(settings.log_level)
    holder: dict[str, Services | None] = {"svc": services}

    def svc() -> Services:
        s = holder["svc"]
        if s is None:
            raise GateError(503, "starting", "gate is starting")
        return s

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if configure_logging:
            setup_logging(settings.log_level)  # uvicorn configures its loggers before import
        if holder["svc"] is None:
            holder["svc"] = Services(settings)
        await holder["svc"].start()
        try:
            yield
        finally:
            await holder["svc"].stop()

    app = FastAPI(
        title="Sekisho gate",
        version="0.1.0",
        description="Compliance checkpoint for AI agent payments (demo policy, not legal advice).",
        lifespan=lifespan,
    )
    origins = [o.strip() for o in settings.console_origin.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    app.add_middleware(RequestLog)
    errors_doc = {c: {"model": ErrorBody} for c in (403, 404, 409, 422, 502)}

    # ---------- errors ----------

    @app.exception_handler(GateError)
    async def _gate_error(_: Request, exc: GateError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": "invalid_request", "message": _validation_message(exc)}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "error")
        return JSONResponse({"error": code, "message": str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse({"error": "internal_error", "message": f"{type(exc).__name__}"}, status_code=500)

    def operator(request: Request) -> None:
        require_operator(request.headers.get("authorization"), settings.sekisho_operator_token)

    # ---------- screening and cases ----------

    @app.post("/v1/screen", responses={200: {"model": ScreeningDecision}, **errors_doc})
    async def screen(req: ScreenRequest, request: Request) -> JSONResponse:
        try:
            validate_payment_asset(req.payment_chain_id, req.asset, settings.usdc_address)
        except ValueError as exc:
            raise GateError(422, "invalid_request", str(exc)) from exc
        view = await svc().pipeline.screen(req)
        request.state.case_id = view["case_id"]
        return JSONResponse(view)

    @app.get("/v1/cases", responses={200: {"model": CaseList}, **errors_doc})
    async def list_cases(
        verdict: Verdict | None = None,
        status: CaseStatus | None = None,
        direction: Direction | None = None,
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = Query(None, max_length=64),
    ) -> JSONResponse:
        s = svc()
        rows, next_cursor = s.store.list_cases(
            verdict=verdict, status=status, direction=direction, limit=limit, cursor=cursor
        )
        items = [decision_view(r, settings.explorer_url) for r in rows]
        return JSONResponse({"items": items, "next_cursor": next_cursor})

    def _case_or_404(case_id: str) -> dict[str, Any]:
        row = svc().store.get_case(case_id)
        if row is None:
            raise not_found(f"case {case_id}")
        return row

    @app.get("/v1/cases/{case_id}", responses={200: {"model": CaseDetail}, **errors_doc})
    async def get_case(case_id: str) -> JSONResponse:
        row = _case_or_404(case_id)
        events = svc().store.chain_events_for_case(row["case_id"], row["case_id_b32"])
        return JSONResponse(case_detail_view(row, events, settings.explorer_url))

    def _reporting_buyer() -> str:
        try:
            buyer = signer_from(settings.buyer_agent_pk.get_secret_value())
        except Exception as exc:
            raise GateError(503, "not_configured", "Configured buyer is unavailable") from exc
        if buyer is None:
            raise GateError(503, "not_configured", "BUYER_AGENT_PK is required to verify payment reports")
        return buyer.address

    @app.post("/v1/cases/{case_id}/payment", responses={200: {"model": PaymentAck}, **errors_doc})
    async def report_payment(case_id: str, body: PaymentReport) -> JSONResponse:
        s = svc()
        row = _case_or_404(case_id)
        if row["verdict"] != "ALLOW" or row["direction"] != "outbound":
            raise invalid_state("only outbound ALLOW cases can report payments")
        if body.network != f"eip155:{row['payment_chain_id']}" or row["payment_chain_id"] != 84532:
            raise invalid_state("payment report must match the screened Base Sepolia network")
        if row["status"] == "PAID":
            if row.get("payment_tx") != body.tx_hash or row.get("payment_network") != body.network:
                raise invalid_state("case already PAID with a different payment")
            return JSONResponse({"case_id": case_id, "status": "PAID"})
        if row["status"] != "DECIDED":
            raise invalid_state(f"case status is {row['status']}")
        await verify_payment_receipt(
            settings.contracts_rpc_url, body.tx_hash, chain_id=row["payment_chain_id"],
            token=row["asset"], payer=_reporting_buyer(), payee=row["counterparty"],
            amount=row["amount"], min_timestamp=int(row["created_ts"]),
        )
        if s.store.record_verified_payment(case_id, body.tx_hash, body.network):
            s.store.audit("agent", "payment", case_id, {"tx_hash": body.tx_hash, "network": body.network})
            s.notifier.case_updated(case_id, metrics=True)
        return JSONResponse({"case_id": case_id, "status": "PAID"})

    @app.post("/v1/cases/{case_id}/hold", responses={200: {"model": HoldAck}, **errors_doc})
    async def report_hold(case_id: str, body: HoldReport) -> JSONResponse:
        s = svc()
        row = _case_or_404(case_id)
        if row["verdict"] != "HOLD" or row["direction"] != "outbound":
            raise invalid_state("only outbound HOLD cases have an escrow deposit")
        linked = row.get("hold_id")
        if linked is not None and int(linked) != body.hold_id:
            raise invalid_state(f"case already linked to hold {linked}")
        if row.get("deposit_tx") and row["deposit_tx"] != body.deposit_tx:
            raise invalid_state("case already linked to a different deposit")
        if row["status"] not in ("DECIDED", "HELD_ESCROWED"):
            return JSONResponse({"case_id": case_id, "status": row["status"]})
        payer = _reporting_buyer()
        if s.mb is None:
            raise GateError(503, "not_configured", "MultiBaas escrow address is unavailable")
        try:
            escrow = await s.mb.address_of(settings.escrow_alias)
        except Exception as exc:
            raise GateError(502, "receipt_unavailable", "Could not resolve configured escrow") from exc
        await verify_hold_receipt(
            settings.contracts_rpc_url, body.deposit_tx, chain_id=row["payment_chain_id"],
            escrow=escrow, case_id_b32=row["case_id_b32"], hold_id=body.hold_id,
            payer=payer, payee=row["counterparty"], amount=row["amount"],
            min_timestamp=int(row["created_ts"]),
        )
        status = s.store.record_verified_hold(case_id, body.hold_id, body.deposit_tx)
        s.store.audit("agent", "hold", case_id, {"hold_id": body.hold_id, "deposit_tx": body.deposit_tx})
        s.attestor.track_tx(body.deposit_tx)
        s.notifier.case_updated(case_id, metrics=True)
        return JSONResponse({"case_id": case_id, "status": status})

    @app.post("/v1/cases/{case_id}/decision", dependencies=[Depends(operator)], responses={200: {"model": DecisionResult}, **errors_doc})
    async def decide(case_id: str, body: DecisionRequest) -> JSONResponse:
        result = await svc().attestor.decide(case_id, body.action, body.note)
        return JSONResponse(DecisionResult.model_validate(result).model_dump(mode="json"))

    @app.get("/v1/reports/{report_hash}", responses={200: {"content": {"application/json": {}}}, **errors_doc})
    async def get_report(report_hash: str, request: Request) -> Response:
        if not _HEX32.match(report_hash):
            raise GateError(422, "invalid_request", "report_hash: expect 0x + 64 hex characters")
        data = svc().store.get_report(report_hash.lower())
        if data is None:
            raise not_found(f"report {report_hash}")
        request.state.case_id = svc().store.report_case_id(report_hash)
        return Response(content=data, media_type="application/json")

    # ---------- dashboards ----------

    @app.get("/v1/metrics", responses={200: {"model": Metrics}})
    async def metrics() -> JSONResponse:
        return JSONResponse(svc().notifier.metrics())

    @app.get("/v1/audit", responses={200: {"model": AuditList}, **errors_doc})
    async def audit(
        limit: int = Query(100, ge=1, le=500), case_id: str | None = Query(None, max_length=64)
    ) -> JSONResponse:
        rows = svc().store.list_chain_events(limit=limit, case_id=case_id)
        return JSONResponse({"items": [chain_event_view(r, settings.explorer_url) for r in rows]})

    @app.get("/v1/treasury", responses={200: {"model": Treasury}})
    async def treasury() -> JSONResponse:
        data = await svc().treasury()
        return JSONResponse(Treasury.model_validate(data).model_dump(mode="json"))

    @app.get("/v1/policy", responses={200: {"model": PolicyInfo}})
    async def policy() -> JSONResponse:
        p = svc().policy
        return JSONResponse({"id": p.id, "version": p.version, "name": p.name, "yaml": p.yaml_text, "parsed": p.parsed})

    @app.get("/v1/quota", responses={200: {"model": Quota}, 503: {"model": ErrorBody}})
    async def quota() -> JSONResponse:
        s = svc()
        q = s.quota()
        if q is None:
            raise GateError(503, "unavailable", f"Intercepta client unavailable: {s.client_errors.get('intercepta', '?')}")
        return JSONResponse(Quota.model_validate(q).model_dump(mode="json"))

    @app.get("/v1/stream")
    async def stream(request: Request) -> EventSourceResponse:
        last = parse_last_event_id(request.headers.get("last-event-id"))
        return EventSourceResponse(
            svc().broker.stream(last), ping=KEEPALIVE_S, headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    @app.post("/v1/demo/reset", dependencies=[Depends(operator)], responses={200: {"model": DemoResetResult}, 403: {"model": ErrorBody}})
    async def demo_reset() -> JSONResponse:
        s = svc()
        if not settings.demo_mode:
            raise GateError(403, "demo_mode_only", "demo reset is only available when DEMO_MODE=true")
        archived, overrides = s.store.demo_reset()
        log.info("demo reset", extra={"archived": archived, "overrides_cleared": overrides})
        s.broker.publish("metrics.updated", s.notifier.metrics())
        return JSONResponse({"archived": archived, "overrides_cleared": overrides})

    @app.get("/healthz", responses={200: {"model": Health}})
    async def healthz() -> JSONResponse:
        s = holder["svc"]
        if s is None:
            return JSONResponse({"status": "degraded", "demo_mode": settings.demo_mode, "policy": None, "checks": {}})
        try:
            return JSONResponse(await s.health())
        except Exception as exc:  # always 200
            log.exception("health check failed")
            return JSONResponse(
                {"status": "degraded", "demo_mode": settings.demo_mode,
                 "policy": {"id": s.policy.id, "version": s.policy.version},
                 "checks": {"gate": {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}}}
            )

    app.include_router(build_router(svc))
    return app


app = create_app()
