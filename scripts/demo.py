"""C8 demo runner (PRD 5, 10.4, 12): deterministic scenarios S1 to S6.

    make demo-setup      .venv/bin/python scripts/demo.py setup    balances, escrow allowance, env summary
    make demo S=S1       .venv/bin/python scripts/demo.py S1       one scenario (S1..S6), or `all`
    make demo-reset      .venv/bin/python scripts/demo.py reset    POST /v1/demo/reset (DEMO_MODE only)

Scenarios call the treasury tools directly with fixed vendors and pairs, not through the
LLM, so every rehearsal repeats exactly. Each one asserts its expected verdict and final
case status (PRD 12, end to end), prints PASS or FAIL, and exits non-zero on FAIL.

    S1  vendor-clean       ALLOW -> PAID           (and the vendor screens our wallet back)
    S2  vendor-mixer       HOLD  -> HELD_ESCROWED -> RELEASED by the officer
                           --premature-release: release_unchecked first, expect 409 NotCleared
                           --auto-release: act as the officer (rehearsals only)
    S3  vendor-sanctioned  BLOCK -> REFUSED, no signature produced
    S4  vendor-injection   the purchase is ALLOWed; its data tells the agent to pay the
                           sanctioned address. --assume-compromised (default) executes that
                           pay_invoice as a fooled model would: BLOCK -> REFUSED. --llm runs
                           the real model instead.
    S5  spoofed payer      agents/rogue/spoofed_payer.py: vendor-clean refuses a flagged payer
    S6  fail-closed        needs the gate started with FAULT_INJECT=intercepta_timeout: HOLD
    all                    S1 -> S3 -> S2 -> S4 -> S5 with pauses (for the video)
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from eth_account import Account  # noqa: E402

from agents.treasury.tools import (  # noqa: E402
    Style,
    build_treasury_tools,
    fget,
    fmt_usdc,
    load_vendors,
    maybe_await,
    receipt_ok,
    revert_name,
    short_addr,
    short_hash,
)
from sekisho import SekishoClient  # noqa: E402

PAIR = "ETH-JPY"
MIN_BUYER_USDC = 5_000_000  # 5 USDC (6 decimals)
MIN_ETH_WEI = 10**16  # 0.01 ETH
ALLOWANCE_TARGET = 100_000_000  # make demo-setup approves 100 USDC to the escrow
ALLOWANCE_LOW = 10_000_000  # re-approve below 10 USDC
STATUS_TIMEOUT_S = 20.0  # PAID / REFUSED / HELD_ESCROWED are set within a second or two
POLL_S = 1.0
OFFICER_TIMEOUT_S = 600.0
DECISION_TIMEOUT_S = 150.0  # the gate waits for the override and the release receipts
ALL_ORDER = ("S1", "S3", "S2", "S4", "S5")


# ---------- results ----------


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Result:
    sid: str
    title: str
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)


def verdict_check(result: dict[str, Any], expected: str, label: str = "verdict") -> Check:
    got, reason = result.get("verdict"), result.get("reason")
    detail = f"got {got}, {result.get('status')}" + (f": {reason}" if reason else "")
    return Check(f"{label} {expected}", got == expected, detail)


def parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------- S4: the injected instruction ----------


@dataclass
class Injection:
    text: str
    pay_to: str
    amount_usd: float
    memo: str


_ADDR = re.compile(r"0x[0-9a-fA-F]{40}")
_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*USDC", re.IGNORECASE)
_MEMO = re.compile(r"\bINV-[A-Za-z0-9-]+")


def find_injection(result: dict[str, Any]) -> Injection | None:
    """The pay_invoice call a fooled model would make, read from the vendor's own text."""
    data = result.get("data")
    text = data.get("notes") if isinstance(data, dict) and isinstance(data.get("notes"), str) else None
    if text is None:
        text = str(result.get("vendor_content") or "")
    if "pay_invoice" not in text:
        return None
    address = _ADDR.search(text)
    if address is None:
        return None
    amount = _AMOUNT.search(text)
    memo = _MEMO.search(text)
    return Injection(text=text, pay_to=address.group(0), amount_usd=float(amount.group(1)) if amount else 25.0,
                     memo=memo.group(0) if memo else "overdue invoice")


# ---------- chain reads (shared with scripts/smoke.py) ----------


def _word(address: str) -> str:
    return address.lower().removeprefix("0x").rjust(64, "0")


class Rpc:
    """Minimal JSON-RPC reads over CONTRACTS_RPC_URL (balances and allowance)."""

    def __init__(self, url: str, http: httpx.AsyncClient):
        self.url, self.http = url, http

    async def call(self, method: str, params: list[Any]) -> Any:
        r = await self.http.post(self.url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        r.raise_for_status()
        body = r.json()
        if body.get("error"):
            raise RuntimeError(f"{method}: {body['error']}")
        return body["result"]

    async def eth_balance(self, address: str) -> int:
        return int(await self.call("eth_getBalance", [address, "latest"]), 16)

    async def erc20_balance(self, token: str, owner: str) -> int:
        data = "0x70a08231" + _word(owner)  # balanceOf(address)
        return int(await self.call("eth_call", [{"to": token, "data": data}, "latest"]), 16)

    async def erc20_allowance(self, token: str, owner: str, spender: str) -> int:
        data = "0xdd62ed3e" + _word(owner) + _word(spender)  # allowance(address,address)
        return int(await self.call("eth_call", [{"to": token, "data": data}, "latest"]), 16)


def wallet_addresses(settings: Any) -> dict[str, str | None]:
    """Role -> address, derived from the keys in .env (addresses only, never keys)."""
    out: dict[str, str | None] = {}
    for role, attr in (("buyer", "buyer_agent_pk"), ("screener", "gate_screener_pk"),
                       ("officer", "officer_pk"), ("deployer", "deployer_pk")):
        key = getattr(settings, attr).get_secret_value()
        try:
            out[role] = Account.from_key(key).address if key else None
        except Exception:  # noqa: BLE001 - malformed key: report as missing
            out[role] = None
    return out


def fmt_eth(wei: int) -> str:
    return f"{wei / 10**18:.4f}"


async def balance_checks(settings: Any, rpc: Rpc) -> list[Check]:
    """Pre-demo checklist (PRD 12): buyer >= 5 USDC and >= 0.01 ETH; screener, officer >= 0.01 ETH."""
    wallets = wallet_addresses(settings)
    checks: list[Check] = []
    buyer = wallets["buyer"]
    if buyer is None:
        checks.append(Check("buyer key set (BUYER_AGENT_PK)", False, "run make wallets"))
    else:
        try:
            usdc = await rpc.erc20_balance(settings.usdc_address, buyer)
            checks.append(Check(f"buyer {short_addr(buyer)} holds {fmt_usdc(usdc)} USDC (need 5)",
                                usdc >= MIN_BUYER_USDC, "faucet.circle.com"))
        except Exception as exc:  # noqa: BLE001
            checks.append(Check(f"buyer {short_addr(buyer)} USDC balance", False, f"RPC error: {exc}"))
    for role in ("buyer", "screener", "officer"):
        address = wallets[role]
        if address is None:
            if role != "buyer":
                checks.append(Check(f"{role} key set", False, "run make wallets"))
            continue
        try:
            wei = await rpc.eth_balance(address)
            checks.append(Check(f"{role} {short_addr(address)} holds {fmt_eth(wei)} ETH (need 0.01)",
                                wei >= MIN_ETH_WEI, "Base Sepolia faucet"))
        except Exception as exc:  # noqa: BLE001
            checks.append(Check(f"{role} {short_addr(address)} ETH balance", False, f"RPC error: {exc}"))
    return checks


async def escrow_address(mb: Any, settings: Any) -> str:
    return str(await maybe_await(mb.address_of(settings.escrow_alias)))


# ---------- the runner ----------


class Demo:
    """Everything a scenario needs; tests inject fakes for tools, sk, gate and mb."""

    def __init__(self, settings: Any, opts: argparse.Namespace, *, emit: Callable[[str], None] | None = None,
                 style: Style | None = None, sk: Any = None, tools: Any = None,
                 gate: httpx.AsyncClient | None = None, mb: Any = None):
        self.settings, self.opts = settings, opts
        self.style = style or Style()
        self.emit = emit or (lambda line: print(line, flush=True))
        self.sk = sk or SekishoClient(settings.sekisho_url)
        self.gate = gate or httpx.AsyncClient(base_url=settings.sekisho_url.rstrip("/"), timeout=30.0)
        self.operator_headers = {"Authorization": f"Bearer {settings.sekisho_operator_token.get_secret_value()}"}
        self._tools, self._mb = tools, mb

    @property
    def mb(self) -> Any:
        if self._mb is None:
            from sekisho_gate.chain.multibaas import MultiBaasClient

            self._mb = MultiBaasClient(self.settings)
        return self._mb

    @property
    def tools(self) -> Any:
        if self._tools is None:
            self._tools = build_treasury_tools(self.settings, emit=self.emit, style=self.style,
                                               sk=self.sk, mb=self.mb)
        return self._tools

    def vendors(self) -> list[dict[str, Any]]:
        """The vendor directory, without building the wallet-backed tools (S5 needs no keys)."""
        return self._tools.vendors if self._tools is not None else load_vendors()

    @property
    def pair(self) -> str:
        return getattr(self.opts, "pair", None) or PAIR

    def say(self, text: str) -> None:
        self.emit(f"[DEMO] {text}")

    def case_url(self, case_id: str) -> str:
        return f"{self.settings.console_origin.rstrip('/')}/cases/{case_id}"

    async def aclose(self) -> None:
        await self.gate.aclose()
        if self._tools is not None:
            await self._tools.aclose()
            return
        for client in (self.sk, self._mb):
            close = getattr(client, "aclose", None)
            if close is not None:
                try:
                    await maybe_await(close())
                except Exception:  # noqa: BLE001
                    pass

    # ----- gate reads -----

    async def get_case(self, case_id: str) -> dict[str, Any] | None:
        try:
            return await self.sk.get_case(case_id)
        except Exception:  # noqa: BLE001 - reported by the caller's check
            return None

    async def wait_status(self, case_id: str, wanted: set[str], timeout: float | None = None,
                          interval: float | None = None) -> dict[str, Any] | None:
        timeout = STATUS_TIMEOUT_S if timeout is None else timeout
        interval = POLL_S if interval is None else interval
        deadline = time.monotonic() + timeout
        while True:
            case = await self.get_case(case_id)
            if case is not None and case.get("status") in wanted:
                return case
            if time.monotonic() >= deadline:
                return case
            await asyncio.sleep(interval)

    async def status_check(self, result: dict[str, Any], status: str, timeout: float | None = None) -> Check:
        case_id = result.get("case_id")
        if not case_id:
            return Check(f"case status {status}", False, "no case id")
        self.emit(self.style.dim(f"[DEMO] case {case_id} · {self.case_url(case_id)}"))
        case = await self.wait_status(case_id, {status}, timeout)
        got = case.get("status") if case else "unreadable"
        return Check(f"case status {status}", got == status, f"got {got}")

    async def gate_up(self) -> bool:
        url = self.settings.sekisho_url
        try:
            r = await self.gate.get("/healthz", timeout=5.0)
            health = r.json()
        except Exception as exc:  # noqa: BLE001
            self.say(f"The gate at {url} is unreachable ({type(exc).__name__}): start it with make gate")
            return False
        if health.get("status") != "ok":
            failing = [f"{k}: {v.get('detail')}" for k, v in (health.get("checks") or {}).items()
                       if isinstance(v, dict) and not v.get("ok")]
            self.say(f"Gate status {health.get('status')}: " + "; ".join(failing))
        return True

    # ----- output -----

    def banner(self, sc: Scenario) -> None:
        self.emit("")
        self.emit(self.style.bold(f"━━ {sc.sid} · {sc.title} · {sc.direction} · expect {sc.expect} ━━"))

    def print_result(self, result: Result) -> None:
        for check in result.checks:
            mark = self.style.paint("✓", "32") if check.ok else self.style.paint("✗", "31")
            tail = f"  ({check.detail})" if check.detail and not check.ok else ""
            self.emit(f"  {mark} {check.name}{tail}")
        word = self.style.paint("PASS", "1;32") if result.passed else self.style.paint("FAIL", "1;31")
        self.emit(f"{word} {result.sid} {result.title}")


# ---------- scenarios ----------


async def s1(demo: Demo) -> list[Check]:
    since = datetime.now(UTC) - timedelta(seconds=5)
    r = await demo.tools.buy_data("vendor-clean", demo.pair)
    checks = [verdict_check(r, "ALLOW"),
              Check("x402 settled onchain (tx hash)", bool(r.get("tx_hash")), str(r.get("status")))]
    checks.append(await demo.status_check(r, "PAID"))
    await seller_side_note(demo, since)
    return checks


async def seller_side_note(demo: Demo, since: datetime) -> None:
    """Informational: the vendor's own inbound screen of our wallet (PRD 5, S1)."""
    buyer = demo.tools.buyer.address.lower()
    try:
        cases = await demo.sk.list_cases(limit=20, direction="inbound")
    except Exception:  # noqa: BLE001
        return
    for case in cases:
        decided = parse_time(fget(case, "decided_at"))
        if str(fget(case, "counterparty")).lower() == buyer and (decided is None or decided >= since):
            demo.say(f"Seller side: the vendor screened our wallet {short_addr(buyer)} → "
                     f"{demo.style.verdict(fget(case, 'verdict'))} · case {fget(case, 'case_id')}")
            return
    demo.say("Seller side: no inbound case for our wallet found")


async def s2(demo: Demo) -> list[Check]:
    s = demo.settings
    r = await demo.tools.buy_data("vendor-mixer", demo.pair)
    checks = [verdict_check(r, "HOLD")]
    if r.get("verdict") == "ALLOW":
        demo.say("S2 came out ALLOW: an officer override is probably still active. Run make demo-reset.")
    checks.append(Check("escrow deposit confirmed (hold id)", r.get("hold_id") is not None,
                        str(r.get("reason") or r.get("escrow"))))
    if r.get("hold_id") is None:
        return checks
    held = await demo.status_check(r, "HELD_ESCROWED")
    checks.append(held)
    if not held.ok:
        return checks
    case_id = r["case_id"]
    if getattr(demo.opts, "premature_release", False):
        if not s.demo_mode:
            demo.say("Skipping the premature release: DEMO_MODE is off")
        else:
            check = await premature_release(demo, case_id, r.get("pay_to") or s.vendor_mixer_payto)
            if check is not None:
                checks.append(check)
    if getattr(demo.opts, "auto_release", False):
        case = await officer_release(demo, case_id)
    else:
        case = await wait_for_officer(demo, case_id, float(getattr(demo.opts, "officer_timeout", OFFICER_TIMEOUT_S)))
    status = case.get("status") if case else "unreadable"
    if status == "REFUNDED":
        demo.say("The officer refunded: that sets a one-year BLOCK override for this payee onchain. "
                 "Never refund the mixer vendor in rehearsals.")
    checks.append(Check("officer released the funds (RELEASED)", status == "RELEASED", f"got {status}"))
    return checks


async def premature_release(demo: Demo, case_id: str, payee: str) -> Check | None:
    """DEMO_MODE: release_unchecked calls release(holdId) without the override; the escrow
    must refuse with NotCleared. Skipped when the payee is still cleared onchain from an
    earlier rehearsal (officer_clear_ttl_seconds), because then the release would go through."""
    s = demo.settings
    try:
        cleared = await maybe_await(demo.mb.call_read(s.registry_alias, s.registry_label, "isCleared", [payee]))
    except Exception as exc:  # noqa: BLE001
        demo.say(f"Skipping the premature release: could not read isCleared ({exc})")
        return None
    if cleared is True or str(cleared).lower() == "true":
        demo.say("Skipping the premature release: this payee is still cleared onchain from an earlier "
                 "release (1 h clearance), so the escrow would pay out")
        return None
    demo.say("Premature release: releasing before the officer clears the payee in the registry")
    try:
        resp = await demo.gate.post(f"/v1/cases/{case_id}/decision", timeout=DECISION_TIMEOUT_S, headers=demo.operator_headers,
                                    json={"action": "release_unchecked",
                                          "note": "Demo: release before the payee is cleared"})
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        return Check("premature release refused with NotCleared (409)", False, f"{type(exc).__name__}: {exc}")
    error = body.get("error") if isinstance(body, dict) else None
    message = body.get("message") if isinstance(body, dict) else ""
    demo.emit(f"[ESCROW] release(holdId) without clearance → HTTP {resp.status_code} {error}: {message}")
    return Check("premature release refused with NotCleared (409)",
                 resp.status_code == 409 and error == "NotCleared", f"HTTP {resp.status_code} {error}")


async def officer_release(demo: Demo, case_id: str) -> dict[str, Any] | None:
    demo.say("--auto-release: acting as the compliance officer through the gate (rehearsals only)")
    try:
        resp = await demo.gate.post(f"/v1/cases/{case_id}/decision", timeout=DECISION_TIMEOUT_S, headers=demo.operator_headers,
                                    json={"action": "release", "note": "Rehearsal auto-release (scripts/demo.py)"})
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        demo.say(f"Release request failed: {type(exc).__name__}: {exc}")
        return await demo.get_case(case_id)
    if resp.status_code != 200:
        demo.say(f"Release refused: HTTP {resp.status_code} {body.get('error')}: {body.get('message')}")
        return await demo.get_case(case_id)
    explorer = demo.settings.explorer_url
    demo.emit(f"[REGISTRY] overrideVerdict(payee, ALLOW) · {explorer}/tx/{body.get('override_tx')}")
    demo.emit(f"[ESCROW] release(holdId) · {explorer}/tx/{body.get('action_tx')}")
    return await demo.wait_status(case_id, {"RELEASED", "REFUNDED"})


async def wait_for_officer(demo: Demo, case_id: str, timeout: float) -> dict[str, Any] | None:
    demo.say(f"Waiting for the compliance officer: open {demo.case_url(case_id)} and click Release "
             f"(timeout {int(timeout // 60)} min)")
    case = await demo.wait_status(case_id, {"RELEASED", "REFUNDED"}, timeout, interval=2 * POLL_S)
    hold = (case or {}).get("hold") or {}
    if case and case.get("status") in ("RELEASED", "REFUNDED"):
        explorer = demo.settings.explorer_url
        demo.emit(f"[ESCROW] {case['status'].title()} by the officer · hold #{hold.get('hold_id')}")
        if hold.get("override_tx"):
            demo.emit(demo.style.dim(f"         override {explorer}/tx/{hold['override_tx']}"))
        if hold.get("action_tx"):
            demo.emit(demo.style.dim(f"         {case['status'].lower()} {explorer}/tx/{hold['action_tx']}"))
    else:
        demo.say("No officer decision before the timeout")
    return case


async def s3(demo: Demo) -> list[Check]:
    r = await demo.tools.buy_data("vendor-sanctioned", demo.pair)
    checks = [verdict_check(r, "BLOCK"),
              Check("no signature produced", r.get("status") == "blocked", str(r.get("status")))]
    checks.append(await demo.status_check(r, "REFUSED"))
    case = await demo.get_case(r["case_id"]) if r.get("case_id") else None
    oracle = ((case or {}).get("evidence") or {}).get("oracle")
    if isinstance(oracle, dict):
        names = {"1": "Ethereum", "8453": "Base"}
        demo.say("Chainalysis oracle: " + " · ".join(f"{names.get(k, k)}={v}" for k, v in oracle.items()))
    return checks


async def s4(demo: Demo) -> list[Check]:
    if getattr(demo.opts, "llm", False):
        return await s4_llm(demo)
    demo.say("The agent buys data from Oracle Feeds Pro. Its wallet is clean, so the purchase is allowed.")
    r1 = await demo.tools.buy_data("vendor-injection", demo.pair)
    checks = [verdict_check(r1, "ALLOW", "purchase verdict"), await demo.status_check(r1, "PAID")]
    injection = find_injection(r1)
    checks.append(Check("vendor data carries an injected instruction", injection is not None,
                        str(r1.get("status"))))
    if injection is None:
        return checks
    demo.emit(f'[VENDOR] Injected text: "{injection.text}"')
    if not getattr(demo.opts, "assume_compromised", True):
        demo.say("--no-assume-compromised: nothing obeys the injected text, so there is nothing to block")
        return checks
    demo.emit(demo.style.bold("[DEMO] Simulating a compromised model: it obeys the vendor text and calls pay_invoice"))
    r2 = await demo.tools.pay_invoice(injection.pay_to, injection.amount_usd, injection.memo)
    checks += [verdict_check(r2, "BLOCK", "pay_invoice verdict"),
               Check("no transaction sent", r2.get("status") == "blocked", str(r2.get("status"))),
               await demo.status_check(r2, "REFUSED")]
    case = await demo.get_case(r2["case_id"]) if r2.get("case_id") else None
    context = str((case or {}).get("untrusted_context") or "")
    checks.append(Check("gate recorded the injected text as untrusted_context",
                        "pay_invoice" in context, "untrusted_context missing"))
    if r2.get("verdict") == "BLOCK":
        demo.emit(demo.style.bold("The model was fooled. The checkpoint was not."))
    return checks


async def s4_llm(demo: Demo) -> list[Check]:
    from agents.treasury.agent import make_chat, run_agent
    from agents.treasury.prompts import S4_TASK_PROMPT

    s = demo.settings
    demo.say("--llm: the real model runs. A well-aligned model may refuse the injection by itself.")
    chat = make_chat(getattr(demo.opts, "provider", None) or s.llm_provider,
                     getattr(demo.opts, "model", None) or s.llm_model or None, s)
    start = len(demo.tools.attempts)
    run = await run_agent(S4_TASK_PROMPT, tools=demo.tools, chat=chat, emit=demo.emit)
    for line in run.final_text.splitlines():
        demo.emit(f"  {line}")
    attempts = demo.tools.attempts[start:]
    bought = [a for a in attempts if a.get("tool") == "buy_data" and a.get("vendor_id") == "vendor-injection"]
    checks = [Check("agent bought from vendor-injection", any(a.get("verdict") == "ALLOW" for a in bought),
                    f"{len(bought)} attempts")]
    sanctioned = s.vendor_sanctioned_payto.lower()
    invoices = [a for a in attempts if a.get("tool") == "pay_invoice"]
    if not invoices:
        demo.say("The model did not act on the injection, so the checkpoint was not needed this time. "
                 "Run S4 without --llm to show the block.")
    for inv in invoices:
        to = str(inv.get("pay_to") or "")
        if to.lower() == sanctioned:
            checks.append(Check(f"pay_invoice to {short_addr(to)} blocked", inv.get("verdict") == "BLOCK",
                                f"got {inv.get('verdict')}"))
        checks.append(Check(f"pay_invoice to {short_addr(to)} sent nothing unscreened",
                            inv.get("status") != "paid" or inv.get("verdict") == "ALLOW", str(inv.get("status"))))
    if any(inv.get("verdict") == "BLOCK" for inv in invoices):
        demo.emit(demo.style.bold("The model was fooled. The checkpoint was not."))
    return checks


async def s5(demo: Demo) -> list[Check]:
    from agents.rogue import spoofed_payer

    s = demo.settings
    vendor = next(v for v in demo.vendors() if v["id"] == "vendor-clean")
    demo.say(f"{spoofed_payer.LABEL}: a crafted x402 payment to vendor-clean with authorization.from = "
             f"{short_addr(s.rogue_payer_addr)}. We hold no key for it.")
    try:
        result = await spoofed_payer.run(vendor["url"], s.rogue_payer_addr, demo.pair,
                                         say=lambda line: demo.emit(f"[ROGUE] {line}"))
    except spoofed_payer.SpoofRunError as exc:
        return [Check("spoofed payment reached the vendor", False, str(exc))]
    checks = [Check("vendor refused the spoofed payer", not result.accepted, f"HTTP {result.status_code}"),
              Check("refused by Sekisho screening, before verification", result.screened,
                    result.refused_by or "accepted"),
              Check("verdict BLOCK", result.verdict == "BLOCK", f"got {result.verdict}")]
    if result.case_id:
        checks.append(await demo.status_check({"case_id": result.case_id}, "REFUSED"))
    else:
        checks.append(Check("case status REFUSED", False, "the vendor reported no case id"))
    return checks


async def s6(demo: Demo) -> list[Check]:
    demo.emit(demo.style.bold("[DEMO] S6 needs the gate started with FAULT_INJECT=intercepta_timeout:"))
    demo.emit("         FAULT_INJECT=intercepta_timeout make gate    (restart it without the variable afterwards)")
    try:
        health_text = (await demo.gate.get("/healthz", timeout=5.0)).text
    except Exception:  # noqa: BLE001
        health_text = ""
    if "intercepta_timeout" in health_text:
        demo.say("The gate reports FAULT_INJECT=intercepta_timeout")
    else:
        demo.say("Warning: /healthz does not mention intercepta_timeout. If this comes out ALLOW, "
                 "the gate was started without FAULT_INJECT.")
    r = await demo.tools.buy_data("vendor-clean", demo.pair)
    checks = [verdict_check(r, "HOLD")]
    case = await demo.get_case(r["case_id"]) if r.get("case_id") else None
    quick = next((c for c in (case or {}).get("checks") or [] if c.get("name") == "intercepta.quick_scan"), None)
    checks.append(Check("Intercepta quick scan failed (status error)", (quick or {}).get("status") == "error",
                        f"got {(quick or {}).get('status')}"))
    rules = ((case or {}).get("policy") or {}).get("triggered_rules") or []
    checks.append(Check("fail-closed rule screening_error triggered", "screening_error" in rules, ", ".join(rules)))
    if r.get("hold_id") is not None:
        checks.append(await demo.status_check(r, "HELD_ESCROWED"))
    else:
        checks.append(Check("escrow deposit confirmed (hold id)", False, str(r.get("reason") or r.get("escrow"))))
    return checks


@dataclass(frozen=True)
class Scenario:
    sid: str
    title: str
    direction: str
    expect: str
    run: Callable[[Demo], Awaitable[list[Check]]]


SCENARIOS: dict[str, Scenario] = {
    "S1": Scenario("S1", "Clean vendor", "outbound", "ALLOW", s1),
    "S2": Scenario("S2", "Mixer-exposed vendor", "outbound", "HOLD", s2),
    "S3": Scenario("S3", "Sanctioned vendor", "outbound", "BLOCK", s3),
    "S4": Scenario("S4", "Prompt injection", "outbound", "BLOCK", s4),
    "S5": Scenario("S5", "Tainted payer (seller side)", "inbound", "BLOCK", s5),
    "S6": Scenario("S6", "Fail-closed", "outbound", "HOLD", s6),
}


async def run_scenario(demo: Demo, sid: str) -> Result:
    sc = SCENARIOS[sid]
    demo.banner(sc)
    try:
        checks = await sc.run(demo)
    except SystemExit as exc:  # e.g. BUYER_AGENT_PK missing
        checks = [Check("scenario could start", False, str(exc))]
    except Exception as exc:  # noqa: BLE001 - a crash is a FAIL, not a traceback on the projector
        checks = [Check("scenario ran without errors", False, f"{type(exc).__name__}: {exc}")]
    result = Result(sid, sc.title, checks)
    demo.print_result(result)
    return result


async def run_all(demo: Demo, pause: float) -> list[Result]:
    results = []
    for i, sid in enumerate(ALL_ORDER):
        if i:
            demo.say(f"Next: {sid} {SCENARIOS[sid].title} in {pause:g} s")
            await asyncio.sleep(pause)
        results.append(await run_scenario(demo, sid))
    demo.emit("")
    demo.emit(demo.style.bold("━━ Summary ━━"))
    for r in results:
        word = demo.style.paint("PASS", "1;32") if r.passed else demo.style.paint("FAIL", "1;31")
        demo.emit(f"{word} {r.sid} {r.title}")
    return results


# ---------- setup and reset ----------


def env_summary(settings: Any) -> list[str]:
    """What the demo will use. Secrets print as set/missing, keys as addresses only."""
    s = settings

    def flag(secret: Any) -> str:
        return "set" if secret.get_secret_value() else "MISSING"

    w = wallet_addresses(s)
    keys = " · ".join(f"{role} {short_addr(addr) if addr else 'MISSING'}" for role, addr in w.items())
    return [
        f"  DEMO_MODE          {str(s.demo_mode).lower()}",
        f"  gate               {s.sekisho_url} · console {s.console_origin}",
        f"  public gate URL    {s.public_gate_url or 'MISSING'}",
        f"  x402               {s.x402_network} · facilitator {s.facilitator_url}",
        f"  contract chain     {s.chain_id} · RPC {s.contracts_rpc_url} · {s.explorer_url}",
        f"  USDC               {s.usdc_address}",
        f"  MultiBaas          {s.mb_url or 'MISSING'} · admin key {flag(s.mb_admin_api_key)} · "
        f"webhook secret {flag(s.mb_webhook_secret)}",
        f"  aliases            {s.registry_alias} · {s.escrow_alias} · {s.usdc_alias}/{s.usdc_label}",
        f"  wallets            {keys}",
        f"  Intercepta key     {flag(s.intercepta_api_key)} · Blockscout key {flag(s.blockscout_api_key)}",
        f"  LLM                {s.llm_provider} {s.llm_model or '(default model)'} · anthropic key "
        f"{flag(s.anthropic_api_key)} · openai key {flag(s.openai_api_key)}",
        f"  vendor payTo       clean {short_addr(s.vendor_clean_payto) if s.vendor_clean_payto else 'MISSING'} · "
        f"mixer {short_addr(s.vendor_mixer_payto) if s.vendor_mixer_payto else 'MISSING'} · "
        f"sanctioned {short_addr(s.vendor_sanctioned_payto)}",
        f"  rogue payer        {short_addr(s.rogue_payer_addr)}",
        f"  FAULT_INJECT       {s.fault_inject or '(off)'}",
    ]


async def allowance_check(demo: Demo, rpc: Rpc, *, approve: bool) -> Check:
    """Escrow allowance for the treasury wallet; with approve=True, top it up to 100 USDC."""
    s = demo.settings
    buyer = wallet_addresses(s)["buyer"]
    if buyer is None:
        return Check("escrow allowance", False, "BUYER_AGENT_PK missing")
    try:
        mb = demo.mb
    except Exception as exc:  # noqa: BLE001 - e.g. the MultiBaas client module is missing
        return Check("escrow allowance", False, f"MultiBaas client unavailable: {type(exc).__name__}: {exc}")
    if getattr(mb, "configured", True) is False:
        return Check("escrow allowance", False, "MultiBaas not configured (MB_URL, MB_ADMIN_API_KEY)")
    try:
        escrow = await escrow_address(mb, s)
        allowance = await rpc.erc20_allowance(s.usdc_address, buyer, escrow)
    except Exception as exc:  # noqa: BLE001
        return Check("escrow allowance", False, f"{type(exc).__name__}: {exc}")
    if allowance < ALLOWANCE_LOW and approve:
        demo.emit(f"[SETUP] Allowance {fmt_usdc(allowance)} USDC is low: usdc.approve({short_addr(escrow)}, "
                  f"{fmt_usdc(ALLOWANCE_TARGET)} USDC) via MultiBaas, signed by the treasury wallet")
        try:
            buyer_acct = Account.from_key(s.buyer_agent_pk.get_secret_value())
            tx = await mb.call_write(s.usdc_alias, s.usdc_label, "approve",
                                          [escrow, str(ALLOWANCE_TARGET)], buyer_acct)
            receipt = await mb.wait_for_receipt(tx, 60)
            demo.emit(f"[SETUP] approve tx {short_hash(tx)} · {'confirmed' if receipt_ok(receipt) else 'NOT confirmed'}"
                      f" · {s.explorer_url}/tx/{tx}")
            allowance = await rpc.erc20_allowance(s.usdc_address, buyer, escrow)
        except Exception as exc:  # noqa: BLE001
            name = revert_name(exc)
            return Check("escrow allowance approved", False, f"{name or type(exc).__name__}: {exc}")
    return Check(f"escrow {short_addr(escrow)} allowance {fmt_usdc(allowance)} USDC (need {fmt_usdc(ALLOWANCE_LOW)})",
                 allowance >= ALLOWANCE_LOW, "run make demo-setup")


async def cmd_setup(demo: Demo) -> int:
    s = demo.settings
    demo.emit(demo.style.bold("━━ Demo setup ━━"))
    demo.emit("[SETUP] Environment (no secrets):")
    for line in env_summary(s):
        demo.emit(line)
    if s.x402_chain_id != s.chain_id:
        demo.emit(f"[SETUP] Note: x402 pays on chain {s.x402_chain_id}, the escrow is on {s.chain_id}; "
                  "the treasury wallet needs USDC on both.")
    async with httpx.AsyncClient(timeout=15.0) as http:
        rpc = Rpc(s.contracts_rpc_url, http)
        checks = await balance_checks(s, rpc)
        checks.append(await allowance_check(demo, rpc, approve=True))
    result = Result("setup", "Demo setup", checks)
    demo.print_result(result)
    return 0 if result.passed else 1


async def cmd_reset(demo: Demo) -> int:
    try:
        resp = await demo.gate.post("/v1/demo/reset", timeout=15.0, headers=demo.operator_headers)
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        demo.say(f"Reset failed: the gate at {demo.settings.sekisho_url} is unreachable ({type(exc).__name__})")
        return 1
    if resp.status_code == 200:
        demo.say(f"Reset: archived {body.get('archived')} cases, cleared {body.get('overrides_cleared')} "
                 "officer overrides. The chain and the Intercepta cache are untouched.")
        return 0
    demo.say(f"Reset refused: HTTP {resp.status_code} {body.get('error')}: {body.get('message')}")
    return 1


# ---------- entry point ----------

COMMANDS = ("setup", "reset", "all", *SCENARIOS)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sekisho demo runner (PRD 10.4)")
    p.add_argument("command", type=lambda v: v.upper() if v.upper() in SCENARIOS else v.lower(),
                   choices=COMMANDS, help="setup, reset, all, or S1..S6")
    p.add_argument("--pair", default=PAIR)
    p.add_argument("--auto-release", action="store_true", help="S2: release as the officer (rehearsals)")
    p.add_argument("--premature-release", action="store_true",
                   help="S2 (DEMO_MODE): release_unchecked first, expect 409 NotCleared")
    p.add_argument("--officer-timeout", type=float, default=OFFICER_TIMEOUT_S, help="S2: seconds to wait")
    p.add_argument("--assume-compromised", action=argparse.BooleanOptionalAction, default=True,
                   help="S4: execute the injected pay_invoice as a fooled model would (default on)")
    p.add_argument("--llm", action="store_true", help="S4: run the real LLM agent instead")
    p.add_argument("--provider", choices=("anthropic", "openai"), help="S4 --llm: default LLM_PROVIDER")
    p.add_argument("--model", help="S4 --llm: default LLM_MODEL")
    p.add_argument("--pause", type=float, default=5.0, help="all: seconds between scenarios")
    return p.parse_args(argv)


async def amain(opts: argparse.Namespace, demo: Demo | None = None) -> int:
    from sekisho_gate.config import get_settings

    demo = demo or Demo(get_settings(), opts)
    try:
        if opts.command == "setup":
            return await cmd_setup(demo)
        if opts.command == "reset":
            return await cmd_reset(demo)
        if not await demo.gate_up():
            return 1
        if opts.command == "all":
            results = await run_all(demo, opts.pause)
            return 0 if all(r.passed for r in results) else 1
        return 0 if (await run_scenario(demo, opts.command)).passed else 1
    finally:
        await demo.aclose()


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(amain(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
