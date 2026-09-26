"""C6 Sekisho MCP server (PRD 10.5): the gate as tools for any MCP agent.

    .venv/bin/python mcp/server.py            stdio (Claude Desktop, Cursor, Claude Code)
    .venv/bin/python mcp/server.py --http     streamable HTTP on http://127.0.0.1:9000/mcp

Tools call the gate at SEKISHO_URL through the Sekisho SDK. Screening results come from
the gate's deterministic policy; this server adds nothing to them and cannot change them.
A gate it can't reach reads as HOLD (fail closed), never ALLOW.

Claude Desktop config (absolute paths: Desktop does not start in the repo):

    {"mcpServers": {"sekisho": {
        "command": "/abs/path/to/repo/.venv/bin/python",
        "args": ["/abs/path/to/repo/mcp/server.py"],
        "env": {"SEKISHO_URL": "http://localhost:8000"}}}}

This folder has no __init__.py on purpose: a package named `mcp` here would shadow the
installed MCP SDK. Never print to stdout here: in stdio mode it is the JSON-RPC channel.
"""

from __future__ import annotations

import argparse
import sys
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from eth_utils import is_address, to_checksum_address
from mcp.server.mcpserver import MCPServer
from sekisho import SekishoClient, SekishoRequestError, SekishoUnavailable
from sekisho_gate.config import get_settings

AGENT_ID = "mcp-agent"
BASE_SEPOLIA_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # the x402 payment asset (PRD 7.1)
HTTP_HOST, HTTP_PORT, HTTP_PATH = "127.0.0.1", 9000, "/mcp"
UNAVAILABLE = "Screening unavailable, failing closed"

mcp = MCPServer(
    "sekisho",
    instructions=(
        "Sekisho is a compliance checkpoint for agent payments. Call screen_counterparty before "
        "paying a wallet or accepting money from one, and follow its verdict: ALLOW means proceed, "
        "HOLD means wait for a human compliance officer, BLOCK means do not pay. The verdict comes "
        "from a deterministic policy (a demo policy, not legal advice)."
    ),
)


def _gate() -> SekishoClient:
    return SekishoClient(get_settings().sekisho_url)


def _case_url(case_id: str | None) -> str | None:
    return f"{get_settings().console_origin.rstrip('/')}/cases/{case_id}" if case_id else None


def _as_dict(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return dict(obj)


def _atomic(amount_usd: float) -> str:
    try:
        value = Decimal(str(amount_usd))
    except InvalidOperation as exc:
        raise ValueError(f"amount_usd {amount_usd!r} is not a number") from exc
    if not value.is_finite() or value < 0:
        raise ValueError("amount_usd must be a non-negative number")
    return str(int((value * 1_000_000).quantize(Decimal(1), rounding=ROUND_HALF_UP)))  # USDC: 6 decimals


def _summary(decision: Any) -> dict[str, Any]:
    d = _as_dict(decision)
    return {
        "case_id": d.get("case_id"),
        "verdict": d.get("verdict"),
        "risk_score": d.get("risk_score"),
        "headline": d.get("headline"),
        "direction": d.get("direction"),
        "counterparty": d.get("counterparty"),
        "amount_usd": d.get("amount_usd"),
        "status": d.get("status"),
        "decided_at": d.get("decided_at"),
        "case_url": _case_url(d.get("case_id")),
    }


@mcp.tool()
async def screen_counterparty(address: str, direction: str = "outbound", amount_usd: float = 0.0,
                              purpose: str = "") -> dict[str, Any]:
    """Screen an EVM wallet before paying it or accepting money from it.
    Returns verdict (ALLOW, HOLD, BLOCK), risk score, reasons and a case link.

    address: the counterparty wallet (0x…). direction: "outbound" (you pay them) or
    "inbound" (they pay you). amount_usd: the payment size in USD (USDC). purpose: why."""
    if not isinstance(address, str) or not is_address(address):
        raise ValueError(f"address {address!r} is not a valid EVM address")
    if direction not in ("outbound", "inbound"):
        raise ValueError('direction must be "outbound" or "inbound"')
    amount = _atomic(amount_usd)
    settings = get_settings()
    try:
        async with _gate() as sk:
            decision = await sk.screen(
                counterparty=to_checksum_address(address), direction=direction, amount=amount,
                asset=BASE_SEPOLIA_USDC, payment_chain_id=settings.x402_chain_id, source="mcp",
                agent_id=AGENT_ID, purpose=str(purpose)[:2000],
            )
    except SekishoRequestError as exc:
        raise ValueError(f"the gate rejected the request: {exc.message}") from exc
    except Exception as exc:  # noqa: BLE001 - unreachable, timeout, 5xx, bad payload: fail closed
        return {"verdict": "HOLD", "risk_score": None, "headline": UNAVAILABLE, "reasons": [],
                "case_id": None, "case_url": None, "error": f"{type(exc).__name__}: {exc}",
                "advice": "Do not pay until screening succeeds."}
    d = _as_dict(decision)
    quick = next((c for c in d.get("checks") or [] if c.get("name") == "intercepta.quick_scan"), None)
    return {
        "verdict": d["verdict"],
        "risk_score": d["risk_score"],
        "headline": d["headline"],
        "reasons": [{"label": r.get("label"), "detail": r.get("detail"), "source": r.get("source"),
                     "severity": r.get("severity")} for r in d.get("reasons") or []],
        "case_id": d["case_id"],
        "case_url": _case_url(d["case_id"]),
        "direction": d.get("direction"),
        "counterparty": d.get("counterparty"),
        "amount_usd": d.get("amount_usd"),
        "intercepta_ms": (quick or {}).get("latency_ms"),
        "policy": d.get("policy"),
        "report_hash": d.get("report_hash"),
    }


@mcp.tool()
async def get_case(case_id: str) -> dict[str, Any]:
    """Full case with evidence and analyst note."""
    try:
        async with _gate() as sk:
            case = await sk.get_case(case_id)
    except SekishoRequestError as exc:
        raise ValueError(f"case {case_id}: {exc.message or exc.error}") from exc
    except SekishoUnavailable as exc:
        raise RuntimeError(f"the gate is unavailable: {exc.message}") from exc
    return {**case, "case_url": _case_url(case.get("case_id"))}


@mcp.tool()
async def list_recent_decisions(limit: int = 10) -> list[dict[str, Any]]:
    """Latest decisions."""
    limit = max(1, min(int(limit), 100))
    try:
        async with _gate() as sk:
            decisions = await sk.list_cases(limit=limit)
    except SekishoUnavailable as exc:
        raise RuntimeError(f"the gate is unavailable: {exc.message}") from exc
    return [_summary(d) for d in decisions]


@mcp.tool()
async def explain_policy() -> dict[str, Any]:
    """Current policy id, version and thresholds."""
    try:
        async with _gate() as sk:
            policy = await sk.policy()
    except SekishoUnavailable as exc:
        raise RuntimeError(f"the gate is unavailable: {exc.message}") from exc
    parsed = policy.get("parsed") or {}
    t = parsed.get("thresholds") or {}
    return {
        "id": policy.get("id"),
        "version": policy.get("version"),
        "name": policy.get("name"),
        "thresholds": t,
        "hard_block_traits": parsed.get("hard_block_traits"),
        "hold_traits": parsed.get("hold_traits"),
        "info_traits": parsed.get("info_traits"),
        "plain_english": [
            "BLOCK if the Chainalysis sanctions oracle flags the wallet, or Intercepta reports a hard-block trait.",
            f"BLOCK if the Intercepta toxicScore is {t.get('block_score')} or more, or {t.get('taint_block_pct')}% "
            "or more of traced inbound funds came from flagged sources.",
            f"HOLD for a human officer on a hold trait (e.g. mixer transfers), toxicScore {t.get('hold_score')} or "
            f"more, taint {t.get('taint_hold_pct')}% or more, or a first payment above ${t.get('first_time_max_usd')}.",
            "HOLD if the Intercepta scan fails or times out: fail closed, never ALLOW on missing data.",
            "Otherwise ALLOW. A demo policy, not legal advice or a certified AML programme.",
        ],
        "yaml": policy.get("yaml"),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sekisho MCP server (stdio by default)")
    parser.add_argument("--http", action="store_true", help=f"streamable HTTP on :{HTTP_PORT}{HTTP_PATH}")
    parser.add_argument("--host", default=HTTP_HOST, help="--http bind host (localhost-only by default)")
    parser.add_argument("--port", type=int, default=HTTP_PORT)
    args = parser.parse_args(argv)
    if args.http:
        print(f"Sekisho MCP server: http://{args.host}:{args.port}{HTTP_PATH}", file=sys.stderr)
        mcp.run(transport="streamable-http", host=args.host, port=args.port, streamable_http_path=HTTP_PATH)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
