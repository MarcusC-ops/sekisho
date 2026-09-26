"""Treasury Agent tools (PRD 10.3): list_vendors, buy_data and pay_invoice.

Screening lives here, in code, never in the prompt (AGENTS.md rule 2):

- buy_data pays over x402. The Sekisho payer hook runs inside the x402 client before
  anything is signed. A second guard, registered after it, refuses to sign unless the
  exact payment being signed carries an ALLOW decision, so no code path signs unscreened.
- pay_invoice calls the gate itself before any transfer, and treats a gate it can't
  reach as HOLD (fail closed).

No tool, argument or flag skips either check. Vendor text is data: it reaches the model
inside <untrusted_vendor_content> tags (agent.py) and the gate as `untrusted_context`.

Every step prints one line, because this log is on screen during the demo.
"""

from __future__ import annotations

import contextvars
import inspect
import json
import os
import re
import sys
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from eth_account import Account
from eth_utils import is_address, keccak, to_checksum_address
from x402 import x402Client
from x402.http import x402HTTPClient
from x402.http.clients import x402HttpxClient
from x402.http.utils import decode_payment_required_header
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact.register import register_exact_evm_client
from x402.schemas import AbortResult, NoMatchingRequirementsError

from sekisho import (
    CURRENT,
    SekishoClient,
    SekishoUnavailable,
    parse_abort_reason,
    payer_hook,
    unwrap_payment_aborted,
)

from sekisho.x402_hooks import validate_decision, validate_payment

AGENT_ID = "treasury-agent-01"
VENDORS_FILE = Path(__file__).with_name("vendors.json")
SPEND_CAP = "$1"  # x402 per-payment cap: a second guard, independent of Sekisho
USDC_DECIMALS = 6
VENDOR_TIMEOUT_S = 60.0  # 402, screening, sign, vendor-side screening, facilitator settle
RECEIPT_TIMEOUT_S = 60
MAX_UNTRUSTED_CHARS = 16000  # the gate accepts up to 65536
HELD_TOPIC = "0x" + keccak(text="Held(uint256,bytes32,address,address,uint256)").hex()

EXPLORERS = {
    1: "https://etherscan.io",
    8453: "https://basescan.org",
    84532: "https://sepolia.basescan.org",
    11155111: "https://sepolia.etherscan.io",
}
CHAIN_NAMES = {1: "Ethereum", 8453: "Base", 84532: "Base Sepolia", 11155111: "Ethereum Sepolia"}
CHECK_NAMES = {
    "intercepta.quick_scan": "Intercepta quick scan",
    "sanctions.oracle": "sanctions oracle",
    "trace.source_of_funds": "source of funds",
    "intercepta.impersonation": "impersonation",
    "intercepta.token": "token scan",
    "intercepta.deep_scan": "deep scan",
}
# Contract reverts worth a hint on screen (names from ComplianceEscrow and OpenZeppelin ERC20).
REVERT_HINTS = {
    "PayeeBlocked": "an officer BLOCK override is active for this payee (a Refund sets one for a year)",
    "ERC20InsufficientAllowance": "the escrow allowance is too low: run make demo-setup",
    "ERC20InsufficientBalance": "the treasury wallet has too little USDC",
    "ZeroAmount": "the amount is zero",
}

# Per-request state for the logging and guard hooks. The hooks run in the caller's task,
# so each buy_data call sees its own dict (PRD 10.1, verified in x402 2.24.0).
_REQUEST: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("treasury_request")


# ---------- formatting ----------


class Style:
    """ANSI colours on a TTY only (the control API captures plain lines)."""

    VERDICT = {"ALLOW": "1;32", "HOLD": "1;33", "BLOCK": "1;31"}

    def __init__(self, enabled: bool | None = None):
        if enabled is None:
            enabled = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        self.enabled = enabled

    def paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def verdict(self, verdict: Any) -> str:
        text = str(verdict)
        return self.paint(text, self.VERDICT.get(text, "1"))

    def dim(self, text: str) -> str:
        return self.paint(text, "2")

    def bold(self, text: str) -> str:
        return self.paint(text, "1")


def fget(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from a pydantic model, a dict or any object."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def short_addr(address: Any) -> str:
    if not isinstance(address, str) or not address:
        return "?"
    if is_address(address):
        address = to_checksum_address(address)
    return f"{address[:6]}…{address[-4:]}" if len(address) > 12 else address


def short_hash(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "?"
    return f"{value[:10]}…{value[-6:]}" if len(value) > 20 else value


def fmt_usdc(atomic: Any) -> str:
    """"50000" -> "0.05", "25000000" -> "25.00"."""
    try:
        value = Decimal(int(atomic)) / Decimal(10**USDC_DECIMALS)
    except (TypeError, ValueError):
        return str(atomic)
    cents = value.quantize(Decimal("0.01"))
    return f"{cents:f}" if cents == value else f"{value.normalize():f}"


def usd_to_atomic(amount_usd: Any) -> int:
    """USD (= USDC) amount to 6-decimal atomic units, without float rounding surprises."""
    if isinstance(amount_usd, bool):
        raise ValueError("amount_usd must be a number")
    try:
        value = Decimal(str(amount_usd).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"amount_usd {amount_usd!r} is not a number") from exc
    if not value.is_finite():
        raise ValueError("amount_usd must be finite")
    return int((value * 10**USDC_DECIMALS).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def atomic_to_usd(atomic: Any) -> float | None:
    try:
        return float(Decimal(int(atomic)) / Decimal(10**USDC_DECIMALS))
    except (TypeError, ValueError):
        return None


def normalize_pair(pair: Any) -> str:
    text = re.sub(r"[/_ ]", "-", str(pair or "ETH-JPY").strip().upper())
    if not re.fullmatch(r"[A-Z0-9]{2,10}-[A-Z0-9]{2,10}", text):
        raise ValueError(f"pair {pair!r} is not a currency pair like ETH-JPY")
    return text


def sanitize_memo(memo: Any) -> str:
    """Invoice memos may come from counterparty text, so keep them short and on one line."""
    return re.sub(r"\s+", " ", str(memo or "")).strip()[:80]


def chain_of(network: Any) -> int | None:
    try:
        return int(str(network).split(":")[1])
    except (IndexError, ValueError):
        return None


def to_hex32(value: Any) -> str:
    """Normalise a log topic (HexBytes, bytes, str or int) to 0x + 64 lowercase hex."""
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex().rjust(64, "0")
    if isinstance(value, int):
        return f"0x{value:064x}"
    text = str(value).lower()
    return text if text.startswith("0x") else "0x" + text


def receipt_ok(receipt: Any) -> bool:
    status = fget(receipt, "status")
    if isinstance(status, str):
        try:
            status = int(status, 0)
        except ValueError:
            return status.lower() in ("success", "true")
    return status is True or status == 1


def held_hold_id(receipt: Any, case_id_b32: str | None = None) -> int | None:
    """holdId from the escrow's Held event: topics[1] (topics[2] is the caseId)."""
    for log in fget(receipt, "logs") or []:
        topics = [to_hex32(t) for t in (fget(log, "topics") or [])]
        if len(topics) < 2 or topics[0] != HELD_TOPIC:
            continue
        if case_id_b32 and len(topics) > 2 and topics[2] != case_id_b32.lower():
            continue
        return int(topics[1], 16)
    return None


def revert_name(exc: BaseException) -> str | None:
    """The contract error name from a MultiBaasError (duck-typed: `.revert`)."""
    name = getattr(exc, "revert", None)
    if name:
        return str(name)
    text = str(exc)
    for known in REVERT_HINTS:
        if known in text:
            return known
    return None


def real_case_id(case_id: Any) -> str | None:
    """parse_abort_reason may return a placeholder such as "unavailable" when there is no case."""
    return case_id if isinstance(case_id, str) and case_id.startswith("cs_") else None


def find_check(decision: Any, name: str) -> Any:
    for check in fget(decision, "checks") or []:
        if fget(check, "name") == name:
            return check
    return None


def describe_check(check: Any) -> str:
    label = CHECK_NAMES.get(fget(check, "name"), fget(check, "name") or "?")
    status = fget(check, "status")
    if status == "error":
        return f"{label} error ({fget(check, 'error') or 'failed'})"
    if status == "skipped":
        return f"{label} skipped"
    text = f"{label} {fget(check, 'latency_ms')} ms"
    live = fget(check, "live")
    if live is True:
        text += " live"
    elif live is False:
        text += " cached"
    return text


def decision_lines(decision: Any, style: Style) -> list[str]:
    """The [SEKISHO] lines for one verdict: headline, reasons (Intercepta text verbatim), checks."""
    verdict = fget(decision, "verdict")
    quick = find_check(decision, "intercepta.quick_scan")
    if quick is None:
        intercepta = "Intercepta n/a"
    elif fget(quick, "status") == "error":
        intercepta = f"Intercepta error ({fget(quick, 'error') or 'failed'})"
    else:
        intercepta = f"Intercepta {fget(quick, 'latency_ms')} ms"
    lines = [
        f"[SEKISHO] {style.verdict(verdict)} (score {fget(decision, 'risk_score')}) "
        f"{fget(decision, 'headline')} · {intercepta} · case {fget(decision, 'case_id')}"
    ]
    for reason in (fget(decision, "reasons") or [])[:4]:
        source, label, detail = fget(reason, "source"), fget(reason, "label"), fget(reason, "detail")
        if source == "intercepta":
            detail = f'"{detail}"'  # Intercepta's own words, verbatim (AGENTS.md rule 8)
        lines.append(f"          {source} · {label}: {detail}")
    checks = [describe_check(c) for c in (fget(decision, "checks") or []) if fget(c, "status") != "skipped"]
    if checks:
        lines.append(style.dim("          checks: " + " · ".join(checks)))
    return lines


async def maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def load_vendors(path: Path = VENDORS_FILE) -> list[dict[str, Any]]:
    return json.loads(path.read_text())


# ---------- the tools ----------


class TreasuryTools:
    """The three tools the Treasury Agent (and the demo runner) can call.

    Dependencies are injected so tests can use fakes: `sk` is a SekishoClient, `x402_client`
    an x402Client that already carries the Sekisho payer hook (build_x402_client), `mb` a
    MultiBaasClient, `buyer` the treasury wallet (eth_account LocalAccount).
    """

    def __init__(
        self,
        *,
        sk: Any,
        x402_client: x402Client,
        mb: Any,
        buyer: Any,
        settings: Any,
        vendors: list[dict[str, Any]] | None = None,
        emit: Callable[[str], None] | None = None,
        style: Style | None = None,
        http_factory: Callable[[x402HTTPClient], httpx.AsyncClient] | None = None,
        agent_id: str = AGENT_ID,
    ):
        self.sk, self.mb, self.buyer, self.settings = sk, mb, buyer, settings
        self.vendors = vendors if vendors is not None else load_vendors()
        self.emit = emit or (lambda line: print(line, flush=True))
        self.style = style or Style()
        self.agent_id = agent_id
        self._reserved_usdc = 0  # atomic USDC; lifetime of this TreasuryTools run
        self.attempts: list[dict[str, Any]] = []  # every payment attempt, for summaries and asserts
        self._vendor_texts: list[str] = []
        # Registered after the Sekisho payer hook, so it only runs once the gate said ALLOW.
        x402_client.on_before_payment_creation(self._guard_before_sign)
        x402_client.on_after_payment_creation(self._after_sign)
        self._x402_http = x402HTTPClient(x402_client).on_payment_required(self._on_402)
        self._http_factory = http_factory or (
            lambda http_client: x402HttpxClient(http_client, timeout=VENDOR_TIMEOUT_S)
        )

    # ----- directory -----

    def list_vendors(self) -> list[dict[str, Any]]:
        keys = ("id", "name", "url", "description", "price")
        return [{k: v.get(k) for k in keys} for v in self.vendors]

    def vendor(self, vendor_id: str) -> dict[str, Any] | None:
        return next((v for v in self.vendors if v["id"] == vendor_id), None)

    async def call(self, name: str, args: dict[str, Any] | None) -> Any:
        """Dispatch a model tool call. Only the documented arguments are read, so no extra
        argument can change what the tool does (there is nothing to skip)."""
        args = args if isinstance(args, dict) else {}
        if name == "list_vendors":
            return self.list_vendors()
        if name == "buy_data":
            return await self.buy_data(str(args.get("vendor_id", "")), str(args.get("pair") or "ETH-JPY"))
        if name == "pay_invoice":
            return await self.pay_invoice(args.get("pay_to", ""), args.get("amount_usd"), str(args.get("memo", "")))
        return {"status": "error", "reason": f"unknown tool {name!r}"}

    # ----- buy_data: x402 -----

    async def buy_data(self, vendor_id: str, pair: str = "ETH-JPY") -> dict[str, Any]:
        vendor = self.vendor(vendor_id)
        base = {"tool": "buy_data", "vendor_id": vendor_id}
        if vendor is None:
            return self._record({**base, "status": "error", "verdict": None, "case_id": None,
                                 "reason": f"unknown vendor_id {vendor_id!r}; call list_vendors"})
        try:
            pair = normalize_pair(pair)
        except ValueError as exc:
            return self._record({**base, "status": "error", "verdict": None, "case_id": None, "reason": str(exc)})
        base["pair"] = pair
        url = vendor["url"]
        cur: dict[str, Any] = {"url": url, "purpose": f"Buy {pair} market data from {vendor['name']}"}
        untrusted = self.untrusted_context()
        if untrusted:
            cur["untrusted_context"] = untrusted
        req: dict[str, Any] = {"vendor_id": vendor_id, "pair": pair, "ask": None}
        _REQUEST.set(req)
        CURRENT.set(cur)  # a fresh dict right before the request; the payer hook writes "decision" into it
        self.emit(f"[AGENT] buy_data {vendor_id} {pair} · GET {url}?pair={pair}")
        try:
            async with self._http_factory(self._x402_http) as http:
                response = await http.get(url, params={"pair": pair})
                await response.aread()
        except Exception as exc:  # noqa: BLE001 - every failure mode is mapped below, none signs
            result = await self._on_x402_error(exc, vendor, cur, req)
        else:
            result = await self._on_x402_response(response, vendor, cur, req)
        ask = req.get("ask") or {}
        amount = fget(cur.get("decision"), "amount") or ask.get("amount")
        return self._record({**base, "amount_usd": atomic_to_usd(amount), "pay_to": ask.get("pay_to"), **result})

    def _on_402(self, ctx: Any) -> None:
        """x402HTTPClient hook: runs on every 402, before spend controls and screening."""
        try:
            req = _REQUEST.get(None)
            accepts = fget(fget(ctx, "payment_required"), "accepts") or []
            if req is None or not accepts:
                return None
            first = accepts[0]
            ask = {"pay_to": fget(first, "pay_to"), "amount": fget(first, "amount"),
                   "asset": fget(first, "asset"), "network": fget(first, "network")}
            req["ask"] = ask
            self.emit(f"[402] {req['vendor_id']} asks {fmt_usdc(ask['amount'])} USDC → payTo {short_addr(ask['pay_to'])}")
        except Exception:  # noqa: BLE001 - logging must never break the payment flow
            pass
        return None

    def _guard_before_sign(self, ctx: Any) -> AbortResult | None:
        """Runs after the Sekisho payer hook returned None (ALLOW). Signs only if the decision
        in CURRENT is an ALLOW for exactly this payee and amount; otherwise fails closed."""
        try:
            cur = CURRENT.get(None)
            decision = cur.get("decision") if isinstance(cur, dict) else None
            selected = fget(ctx, "selected_requirements")
            pay_to, amount = fget(selected, "pay_to"), fget(selected, "amount")
            if decision is None or fget(decision, "verdict") != "ALLOW":
                return AbortResult(reason="HOLD|unscreened|No Sekisho ALLOW before signing, failing closed")
            validate_decision(decision, counterparty=pay_to, amount=amount,
                              asset=fget(selected, "asset"), chain_id=chain_of(fget(selected, "network")))
            refusal = self._reserve_payment(amount)
            if refusal:
                return AbortResult(reason=f"HOLD|budget|{refusal['reason']}")
            for line in decision_lines(decision, self.style):
                self.emit(line)
            return None
        except Exception:  # noqa: BLE001
            return AbortResult(reason="HOLD|unscreened|Signing guard failed, failing closed")

    def _after_sign(self, ctx: Any) -> None:
        try:
            self.emit("[x402] Signed EIP-3009 USDC authorization (gasless) · retrying with PAYMENT-SIGNATURE")
        except Exception:  # noqa: BLE001
            pass
        return None

    async def _on_x402_error(self, exc: Exception, vendor: dict, cur: dict, req: dict) -> dict[str, Any]:
        vendor_id = vendor["id"]
        aborted = unwrap_payment_aborted(exc)
        if aborted is not None:
            verdict, case_id, headline = parse_abort_reason(getattr(aborted, "reason", str(aborted)))
            return await self._on_abort(verdict, real_case_id(case_id), headline, cur.get("decision"), req,
                                        cause=cur.get("error"))
        cause = _find_cause(exc, NoMatchingRequirementsError)
        if cause is not None:
            if "spend_controls" in str(cause):
                self.emit(f"[AGENT] Refused by the x402 spend cap ({SPEND_CAP} per payment) before screening. "
                          "No signature produced.")
                return {"status": "blocked", "verdict": None, "case_id": None,
                        "reason": f"blocked by spend cap ({SPEND_CAP} per payment); Sekisho was not asked"}
            self.emit(f"[AGENT] {vendor_id} offers no payment terms this wallet can use: {cause}")
            return {"status": "error", "verdict": None, "case_id": None, "reason": f"unsupported payment terms: {cause}"}
        decision = cur.get("decision")
        if isinstance(exc, httpx.HTTPError) and decision is None:
            self.emit(f"[AGENT] {vendor_id} unreachable: {exc!r}")
            return {"status": "error", "verdict": None, "case_id": None, "reason": f"vendor unreachable: {exc}"}
        root = _root_cause(exc)
        if decision is not None and fget(decision, "verdict") == "ALLOW":
            self.emit(f"[AGENT] Payment round trip failed after ALLOW ({root!r}). Settlement unknown: "
                      f"check case {fget(decision, 'case_id')}.")
        else:
            self.emit(f"[AGENT] Request to {vendor_id} failed: {root!r}. No signature produced.")
        return {"status": "error", "verdict": fget(decision, "verdict"), "case_id": fget(decision, "case_id"),
                "reason": f"payment round trip failed: {root}"}

    async def _on_abort(self, verdict: Any, case_id: str | None, headline: Any, decision: Any,
                        req: dict, cause: Any = None) -> dict[str, Any]:
        if case_id is not None and decision is not None:
            for line in decision_lines(decision, self.style):
                self.emit(line)
        else:  # no case: the gate was unreachable, or the signing guard refused
            tail = f" · case {case_id}" if case_id else ""
            self.emit(f"[SEKISHO] {self.style.verdict(verdict)} · {headline}{tail}")
            if cause:  # the SDK records why screening failed
                self.emit(self.style.dim(f"          {cause}"))
        if verdict == "HOLD":
            if case_id is None:
                self.emit("[AGENT] Payment held: no usable screening result (fail closed). No signature produced.")
                return {"status": "held", "verdict": "HOLD", "case_id": None, "escrow": False,
                        "reason": str(headline),
                        "message": "Payment held because screening was unavailable. Nothing was signed."}
            self.emit("[AGENT] Payment aborted before signing. Holding the funds in escrow for compliance review.")
            ask = req.get("ask") or {}
            pay_to = fget(decision, "counterparty") or ask.get("pay_to")
            amount = fget(decision, "amount") or ask.get("amount")
            case_b32 = fget(decision, "case_id_b32") or await self._case_id_b32(case_id)
            return await self._hold_in_escrow(case_id, case_b32, pay_to, amount, str(headline))
        if verdict != "BLOCK":
            self.emit(f"[AGENT] Unrecognised verdict {verdict!r}: refusing (fail closed). No signature produced.")
        else:
            self.emit(f"[AGENT] {self.style.verdict('Payment refused.')} No signature produced.")
        return {"status": "blocked", "verdict": "BLOCK" if verdict == "BLOCK" else verdict, "case_id": case_id,
                "reason": str(headline), "message": "Payment refused by Sekisho. No signature was produced."}

    async def _on_x402_response(self, r: httpx.Response, vendor: dict, cur: dict, req: dict) -> dict[str, Any]:
        vendor_id, decision = vendor["id"], cur.get("decision")
        verdict, case_id = fget(decision, "verdict"), fget(decision, "case_id")
        text = r.text
        if r.status_code == 402:
            reason = self._refusal_reason(r)
            self.emit(f"[VENDOR] {vendor_id} refused our payment: {reason}")
            self._remember_vendor_text(reason)
            return {"status": "refused_by_vendor", "verdict": verdict, "case_id": case_id,
                    "reason": "the vendor refused the payment", "vendor_content": reason}
        if r.status_code == 403:  # the vendor's payer gate: {"error": "payer_refused", "verdict", "case_id", ...}
            try:
                body = r.json()
            except ValueError:
                body = None
            if isinstance(body, dict) and body.get("error") == "payer_refused":
                self.emit(f"[VENDOR] {vendor_id} screened our wallet and refused: {body.get('verdict')} · "
                          f"{body.get('headline') or ', '.join(map(str, body.get('reasons') or []))} · "
                          f"case {body.get('case_id')}")
            else:
                self.emit(f"[VENDOR] {vendor_id} refused our wallet (HTTP 403): {text[:200]}")
            self._remember_vendor_text(text)
            return {"status": "refused_by_vendor", "verdict": verdict, "case_id": case_id,
                    "reason": "the vendor refused our wallet", "vendor_content": text}
        if r.status_code >= 400:
            self.emit(f"[AGENT] {vendor_id} answered HTTP {r.status_code}; x402 does not settle on errors.")
            return {"status": "error", "verdict": verdict, "case_id": case_id,
                    "reason": f"vendor answered HTTP {r.status_code}"}
        settle = self._settle_of(r)
        result: dict[str, Any]
        if decision is None:
            self.emit(f"[AGENT] {vendor_id} returned data without asking for payment.")
            result = {"status": "free", "verdict": None, "case_id": None}
        else:
            self.emit(f"[VENDOR] {vendor_id} screened our wallet {short_addr(self.buyer.address)} and accepted")
            tx = fget(settle, "transaction") if settle is not None and fget(settle, "success") else None
            if tx:
                network = fget(settle, "network") or self.settings.x402_network
                chain = chain_of(network)
                self.emit(f"[x402] Settled on {CHAIN_NAMES.get(chain, network)} · tx {short_hash(tx)}")
                self.emit(self.style.dim(f"       {EXPLORERS.get(chain, self.settings.explorer_url)}/tx/{tx}"))
                await self._report_payment(case_id, tx, network)
                result = {"status": "paid", "verdict": verdict, "case_id": case_id, "tx_hash": tx}
            else:
                self.emit("[x402] Response had no settlement receipt (PAYMENT-RESPONSE); payment unconfirmed")
                result = {"status": "unconfirmed", "verdict": verdict, "case_id": case_id}
        self._remember_vendor_text(text)
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        self.emit(f"[AGENT] Received {req.get('pair', '')} data from {vendor['name']}")
        return {**result, "vendor_content": text, "data": data}

    def _settle_of(self, r: httpx.Response) -> Any:
        try:
            return self._x402_http.get_payment_settle_response(lambda name: r.headers.get(name))
        except Exception:  # noqa: BLE001 - missing or malformed header
            return None

    def _refusal_reason(self, r: httpx.Response) -> str:
        settle = self._settle_of(r)
        if settle is not None and not fget(settle, "success"):
            return f"settlement failed: {fget(settle, 'error_reason') or fget(settle, 'error_message') or 'unknown'}"
        header = r.headers.get("PAYMENT-REQUIRED")
        if header:
            try:
                error = decode_payment_required_header(header).error
                if error:
                    return str(error)
            except Exception:  # noqa: BLE001
                pass
        return "payment required again after paying"

    async def _report_payment(self, case_id: Any, tx: str, network: str) -> None:
        if not case_id:
            return
        try:
            await self.sk.report_payment(case_id, tx, network)
            self.emit(f"[SEKISHO] Settlement reported · case {case_id} → PAID")
        except Exception as exc:  # noqa: BLE001 - the payment happened; reporting is best effort
            self.emit(f"[SEKISHO] Could not report the settlement ({exc}); case {case_id} stays DECIDED")

    # ----- pay_invoice: direct transfer -----

    async def pay_invoice(self, pay_to: Any, amount_usd: Any, memo: str = "") -> dict[str, Any]:
        memo = sanitize_memo(memo)
        base = {"tool": "pay_invoice", "pay_to": pay_to, "memo": memo}
        if not isinstance(pay_to, str) or not is_address(pay_to):
            return self._record({**base, "status": "error", "verdict": None, "case_id": None,
                                 "reason": "pay_to is not a valid EVM address"})
        pay_to = to_checksum_address(pay_to)
        try:
            amount = usd_to_atomic(amount_usd)
        except ValueError as exc:
            return self._record({**base, "status": "error", "verdict": None, "case_id": None, "reason": str(exc)})
        if amount <= 0:
            return self._record({**base, "status": "error", "verdict": None, "case_id": None,
                                 "reason": "amount_usd must be positive"})
        base.update(pay_to=pay_to, amount_usd=atomic_to_usd(amount))
        self.emit(f"[AGENT] pay_invoice {fmt_usdc(amount)} USDC → {short_addr(pay_to)} · memo {memo!r}")
        self.emit("[SEKISHO] Screening the payee before any transfer (direct payment)")
        try:
            decision = await self.sk.screen(
                counterparty=pay_to, direction="outbound", amount=str(amount),
                asset=self.settings.usdc_address, payment_chain_id=self.settings.chain_id,
                source="direct", agent_id=self.agent_id, purpose=f"Direct invoice payment (memo: {memo})",
                resource="", untrusted_context=self.untrusted_context() or None,
            )
        except SekishoUnavailable as exc:
            return self._record({**base, **self._screen_failed(f"gate unreachable: {exc}")})
        except Exception as exc:  # noqa: BLE001 - any screening failure fails closed
            return self._record({**base, **self._screen_failed(f"screening failed: {exc}")})
        try:
            validate_decision(decision, counterparty=pay_to, amount=amount,
                              asset=self.settings.usdc_address, chain_id=self.settings.chain_id)
        except ValueError as exc:
            return self._record({**base, **self._screen_failed(str(exc))})
        for line in decision_lines(decision, self.style):
            self.emit(line)
        verdict, case_id = fget(decision, "verdict"), fget(decision, "case_id")
        headline = str(fget(decision, "headline") or "")
        if verdict == "ALLOW":
            return self._record({**base, **await self._transfer(case_id, pay_to, amount)})
        if verdict == "HOLD":
            self.emit("[AGENT] Invoice held. Depositing the funds into escrow for compliance review.")
            case_b32 = fget(decision, "case_id_b32") or await self._case_id_b32(case_id)
            return self._record({**base, **await self._hold_in_escrow(case_id, case_b32, pay_to, amount, headline)})
        self.emit(f"[AGENT] {self.style.verdict('Payment refused.')} No transaction signed.")
        return self._record({**base, "status": "blocked", "verdict": verdict if verdict else "BLOCK",
                             "case_id": case_id, "reason": headline,
                             "message": "Payment refused by Sekisho. No transaction was signed."})

    def _screen_failed(self, why: str) -> dict[str, Any]:
        self.emit(f"[SEKISHO] {self.style.verdict('HOLD')} · {why} · failing closed. Nothing sent.")
        return {"status": "held", "verdict": "HOLD", "case_id": None, "escrow": False,
                "reason": "Screening unavailable, failing closed",
                "message": "Payment held because screening was unavailable. Nothing was sent."}

    def _reserve_payment(self, amount: Any) -> dict[str, Any] | None:
        # No await between check and reservation: concurrent tools share this budget.
        # Reserve before signing and retain on ambiguous failures; signatures can settle later.
        try:
            atomic = validate_payment(self.settings.usdc_address, self.settings.chain_id, amount)
            if atomic > 1_000_000:
                raise ValueError("Payment exceeds $1 per-payment budget")
            if self._reserved_usdc + atomic > 5_000_000:
                raise ValueError("Payment exceeds $5 per-run budget")
        except ValueError as exc:
            self.emit(f"[AGENT] Payment refused: {exc}. Nothing signed.")
            return {"status": "blocked", "verdict": "HOLD", "case_id": None,
                    "escrow": False, "reason": str(exc)}
        self._reserved_usdc += atomic
        return None

    async def _transfer(self, case_id: Any, pay_to: str, amount: int) -> dict[str, Any]:
        refusal = self._reserve_payment(amount)
        if refusal:
            return refusal
        s = self.settings
        self.emit(f"[CHAIN] usdc.transfer({short_addr(pay_to)}, {fmt_usdc(amount)} USDC) via MultiBaas, "
                  "signed by the treasury wallet")
        try:
            tx = await self.mb.call_write(s.usdc_alias, s.usdc_label, "transfer", [pay_to, str(amount)], self.buyer)
        except Exception as exc:  # noqa: BLE001
            name = revert_name(exc)
            self.emit(f"[CHAIN] Transfer refused: {name or exc}{self._hint(name)}")
            return {"status": "error", "verdict": "ALLOW", "case_id": case_id, "reason": f"transfer failed: {name or exc}"}
        receipt = await self._wait_receipt(tx)
        if receipt is None or not receipt_ok(receipt):
            state = "reverted" if receipt is not None else "not confirmed in time"
            self.emit(f"[CHAIN] Transfer {state}")
            self.emit(self.style.dim(f"        {s.explorer_url}/tx/{tx}"))
            return {"status": "error", "verdict": "ALLOW", "case_id": case_id, "tx_hash": tx,
                    "reason": f"transfer {state}"}
        self.emit(f"[CHAIN] Transfer confirmed · tx {short_hash(tx)}")
        self.emit(self.style.dim(f"        {s.explorer_url}/tx/{tx}"))
        await self._report_payment(case_id, tx, f"eip155:{s.chain_id}")
        return {"status": "paid", "verdict": "ALLOW", "case_id": case_id, "tx_hash": tx}

    # ----- HOLD: escrow deposit -----

    async def _case_id_b32(self, case_id: str) -> str:
        try:
            case = await self.sk.get_case(case_id)
            value = fget(case, "case_id_b32")
            if value:
                return str(value)
        except Exception:  # noqa: BLE001
            pass
        return "0x" + keccak(text=case_id).hex()  # docs/api.md: case_id_b32 = keccak(text=case_id)

    async def _hold_in_escrow(self, case_id: str, case_b32: str, pay_to: Any, amount: Any,
                              headline: str) -> dict[str, Any]:
        s = self.settings
        out: dict[str, Any] = {"status": "held", "verdict": "HOLD", "case_id": case_id, "reason": headline,
                               "hold_id": None, "deposit_tx": None}
        if not isinstance(pay_to, str) or not is_address(pay_to) or not str(amount or "").isdigit():
            self.emit("[ESCROW] Missing payee or amount for the deposit; nothing was sent.")
            return {**out, "escrow": "failed", "message": f"Payment held (not signed), case {case_id}."}
        pay_to = to_checksum_address(pay_to)
        refusal = self._reserve_payment(amount)
        if refusal:
            return refusal
        self.emit(f"[ESCROW] deposit({short_addr(pay_to)}, {fmt_usdc(amount)} USDC, case {short_hash(case_b32)}) "
                  "via MultiBaas, signed by the treasury wallet")
        try:
            tx = await self.mb.call_write(s.escrow_alias, s.escrow_label, "deposit",
                                          [pay_to, str(int(amount)), case_b32], self.buyer)
        except Exception as exc:  # noqa: BLE001
            name = revert_name(exc)
            self.emit(f"[ESCROW] Deposit refused: {name or exc}{self._hint(name)}")
            return {**out, "escrow": "failed", "reason": f"escrow deposit failed: {name or exc}",
                    "message": f"Payment held (not signed), but the escrow deposit failed. Case {case_id}."}
        out["deposit_tx"] = tx
        self.emit(f"[ESCROW] tx {short_hash(tx)} submitted · waiting for confirmation")
        receipt = await self._wait_receipt(tx)
        if receipt is None:
            self.emit("[ESCROW] Not confirmed yet; the Held webhook will link the hold when it lands")
            return {**out, "escrow": "pending", "message": f"Payment held for compliance review, case {case_id}."}
        if not receipt_ok(receipt):
            self.emit(f"[ESCROW] Deposit reverted onchain · tx {short_hash(tx)}")
            self.emit(self.style.dim(f"         {s.explorer_url}/tx/{tx}"))
            return {**out, "escrow": "failed", "reason": "escrow deposit reverted",
                    "message": f"Payment held (not signed), but the escrow deposit reverted. Case {case_id}."}
        hold_id = held_hold_id(receipt, case_b32)
        out.update(hold_id=hold_id, escrow="deposited")
        if hold_id is None:
            self.emit("[ESCROW] Deposit confirmed, but no Held event was found in the receipt")
        else:
            self.emit(f"[ESCROW] Held in ComplianceEscrow · hold #{hold_id}")
            self.emit(self.style.dim(f"         {s.explorer_url}/tx/{tx}"))
            try:
                await self.sk.report_hold(case_id, hold_id, tx)
                self.emit(f"[SEKISHO] Hold #{hold_id} linked to case {case_id} → HELD_ESCROWED")
            except Exception as exc:  # noqa: BLE001 - the Held webhook links it too
                self.emit(f"[SEKISHO] Could not report the hold ({exc}); the Held webhook will link it")
        self.emit(f"[AGENT] Payment held for compliance review, case {case_id}.")
        return {**out, "message": f"Payment held for compliance review, case {case_id}. "
                                  "A compliance officer will release or refund it."}

    async def _wait_receipt(self, tx: str) -> Any:
        try:
            return await self.mb.wait_for_receipt(tx, RECEIPT_TIMEOUT_S)
        except Exception:  # noqa: BLE001 - timeout or RPC error
            return None

    @staticmethod
    def _hint(name: str | None) -> str:
        return f" ({REVERT_HINTS[name]})" if name in REVERT_HINTS else ""

    # ----- untrusted vendor content -----

    def _remember_vendor_text(self, text: str) -> None:
        if text and text not in self._vendor_texts:
            self._vendor_texts.append(text)

    def untrusted_context(self) -> str:
        """Everything vendors sent back this session, verbatim, newest kept when over the cap."""
        kept: list[str] = []
        total = 0
        for text in reversed(self._vendor_texts):
            if total + len(text) > MAX_UNTRUSTED_CHARS and kept:
                break
            kept.append(text[-MAX_UNTRUSTED_CHARS:])
            total += len(kept[-1])
        return "\n\n".join(reversed(kept))

    def _record(self, result: dict[str, Any]) -> dict[str, Any]:
        self.attempts.append(result)
        return result

    async def aclose(self) -> None:
        for client in (self.sk, self.mb):
            close = getattr(client, "aclose", None)
            if close is not None:
                try:
                    await maybe_await(close())
                except Exception:  # noqa: BLE001
                    pass


def _find_cause(exc: BaseException | None, kind: type[BaseException]) -> BaseException | None:
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, kind):
            return exc
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return None


def _root_cause(exc: BaseException) -> BaseException:
    seen = set()
    while (exc.__cause__ or exc.__context__) is not None and id(exc) not in seen:
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return exc


# ---------- construction ----------


def build_x402_client(buyer: Any, sk: Any, agent_id: str = AGENT_ID) -> x402Client:
    """PRD 10.3 x402 client setup, confirmed against x402 2.24.0."""
    client = x402Client()
    register_exact_evm_client(client, EthAccountSigner(buyer))
    client.set_spend_controls({"max_amount_per_payment": SPEND_CAP})  # SDK cap: a second, independent guard
    client.on_before_payment_creation(payer_hook(sk, agent_id))
    return client


def buyer_account(settings: Any) -> Any:
    key = settings.buyer_agent_pk.get_secret_value()
    if not key:
        raise SystemExit("BUYER_AGENT_PK is not set in .env: run make wallets")
    return Account.from_key(key)


def build_treasury_tools(settings: Any = None, *, emit: Callable[[str], None] | None = None,
                         style: Style | None = None, sk: Any = None, mb: Any = None) -> TreasuryTools:
    """The real wiring: SekishoClient at SEKISHO_URL, x402 on Base Sepolia, MultiBaas for writes."""
    from sekisho_gate.config import get_settings

    s = settings or get_settings()
    buyer = buyer_account(s)
    sk = sk or SekishoClient(s.sekisho_url)
    if mb is None:
        from sekisho_gate.chain.multibaas import MultiBaasClient

        mb = MultiBaasClient(s)
    return TreasuryTools(sk=sk, x402_client=build_x402_client(buyer, sk), mb=mb,
                         buyer=buyer, settings=s, emit=emit, style=style)
