"""x402 hooks: screen the counterparty before a payment is signed or accepted (PRD 10.1).

- `payer_hook`: register with `x402Client.on_before_payment_creation` (buyer side). It runs
  after the 402 is parsed and before the scheme signs, so an abort means no signature exists.
- `payee_hook`: register with `x402ResourceServer.on_before_verify` (seller side). It runs
  before the facilitator's verify, the route handler and settlement.

Abort reasons are `VERDICT|case_id|headline`, e.g. `BLOCK|cs_01J…|Counterparty is on a
sanctions list`. Any failure (gate unreachable, timeout, 5xx, bad payload, a bug) aborts
with `HOLD|unavailable|…`: fail closed. Only an `AbortResult` instance aborts in x402, so
the hooks catch every exception and never return anything else.

x402 is an optional extra and is imported lazily, so `import sekisho` works without it.
Verified against x402 2.24.0.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .errors import SekishoUnavailable

if TYPE_CHECKING:
    from .client import SekishoClient
    from .models import Decision

__all__ = [
    "CURRENT",
    "payer_hook",
    "payee_hook",
    "parse_abort_reason",
    "unwrap_payment_aborted",
    "abort_reason",
    "chain_id_from_network",
    "payer_address",
    "screen_payer",
]

log = logging.getLogger("sekisho")

# The agent sets a FRESH dict before every paid request:
#     CURRENT.set({"url": url, "purpose": purpose})          # optional: "untrusted_context"
# The payer hook reads it and writes into it (it never calls .set()):
#     "decision"      the Decision, whenever the gate answered (ALLOW included)
#     "abort_reason"  the AbortResult reason, whenever the hook aborted
#     "error"         "<ExceptionType>: <message>", when screening failed (fail closed)
CURRENT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("sekisho_current")

_VERDICTS = ("ALLOW", "HOLD", "BLOCK")
_UNAVAILABLE_HEADLINE = "Screening unavailable, failing closed"
_V1_CHAIN_IDS = {"base-sepolia": 84532, "base": 8453}  # x402 v1 network names


def _abort_result_cls() -> Any:
    try:
        from x402.schemas import AbortResult
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(
            "Sekisho's x402 hooks need the x402 extra: pip install -e 'sdk[x402]'"
        ) from exc
    return AbortResult


# ---------------------------------------------------------------------------- hooks


BASE_SEPOLIA_CHAIN_ID = 84532
BASE_SEPOLIA_USDC = "0x036cbd53842c5426634e7929541ec2318f3dcf7e"


def validate_payment(asset: str, chain_id: int, amount: Any) -> int:
    """Only canonical testnet USDC can reach a signing path in this demo."""
    if chain_id != BASE_SEPOLIA_CHAIN_ID or str(asset).lower() != BASE_SEPOLIA_USDC:
        raise ValueError("Only Base Sepolia USDC payments are supported")
    if not str(amount).isdigit() or int(amount) <= 0:
        raise ValueError("Payment amount must be positive atomic USDC")
    return int(amount)


def validate_decision(decision: Any, *, counterparty: str, amount: Any,
                      asset: str, chain_id: int, direction: str = "outbound") -> None:
    """Bind the gate verdict to the exact payment; absent binding fields fail closed."""
    validate_payment(asset, chain_id, amount)
    if (str(getattr(decision, "counterparty", "")).lower() != str(counterparty).lower()
            or str(getattr(decision, "amount", "")) != str(amount)
            or str(getattr(decision, "asset", "")).lower() != str(asset).lower()
            or getattr(decision, "payment_chain_id", None) != chain_id
            or getattr(decision, "direction", None) != direction):
        raise ValueError("Screened payment differs from requested payment")


def payer_hook(sk: SekishoClient, agent_id: str) -> Any:
    """Build the buyer-side hook: `client.on_before_payment_creation(payer_hook(sk, agent_id))`.

    ALLOW returns None, so x402 signs and pays. HOLD and BLOCK return an AbortResult, and
    x402 raises PaymentAbortedError before signing. `x402HttpxClient` wraps that error in
    `x402.http.clients.httpx.PaymentError`, so use `unwrap_payment_aborted(exc)` to get it.
    """
    abort_result = _abort_result_cls()  # fail at registration, not at payment time

    async def sekisho_payer_hook(ctx: Any) -> Any:
        cur = CURRENT.get(None)
        if cur is None:  # the agent forgot CURRENT.set(): still screen, just without context
            cur = {}
        try:
            req = ctx.selected_requirements
            validate_payment(req.asset, chain_id_from_network(req.network), _amount(req))
            decision = await sk.screen(
                counterparty=req.pay_to,
                direction="outbound",
                amount=_amount(req),
                asset=req.asset,
                payment_chain_id=chain_id_from_network(req.network),
                source="x402",
                agent_id=agent_id,
                purpose=_text(cur.get("purpose")),
                resource=_text(cur.get("url")),
                untrusted_context=cur.get("untrusted_context"),
            )
            validate_decision(decision, counterparty=req.pay_to, amount=_amount(req),
                              asset=req.asset, chain_id=chain_id_from_network(req.network))
        except Exception as exc:  # noqa: BLE001 - every failure must fail closed
            reason = _failure_reason(exc)
            cur["error"] = f"{type(exc).__name__}: {exc}"
            cur["abort_reason"] = reason
            log.warning("sekisho payer screen failed, holding: %s", cur["error"])
            return abort_result(reason=reason)
        cur["decision"] = decision  # mutate the dict; a ContextVar.set() here would be lost
        if decision.verdict == "ALLOW":
            return None
        cur["abort_reason"] = reason = abort_reason(decision)
        return abort_result(reason=reason)

    return sekisho_payer_hook


def payee_hook(sk: SekishoClient, agent_id: str) -> Any:
    """Build the seller-side hook: `server.on_before_verify(payee_hook(sk, vendor_id))`.

    Screens the payer (`authorization.from`) as an inbound counterparty. On HOLD or BLOCK the
    middleware answers 402 with the reason in the PAYMENT-REQUIRED header's `error` field,
    and neither verify, the route handler nor settle runs.
    """
    abort_result = _abort_result_cls()

    async def sekisho_payee_hook(ctx: Any) -> Any:
        try:
            decision = await screen_payer(
                sk,
                agent_id,
                ctx.payment_payload,
                ctx.requirements,
                resource=resource_from_verify_context(ctx),
            )
        except Exception as exc:  # noqa: BLE001 - every failure must fail closed
            log.warning("sekisho payee screen failed, holding: %s: %s", type(exc).__name__, exc)
            return abort_result(reason=_failure_reason(exc))
        if decision.verdict == "ALLOW":
            return None
        return abort_result(reason=abort_reason(decision))

    return sekisho_payee_hook


async def screen_payer(
    sk: SekishoClient,
    agent_id: str,
    payment_payload: Any,
    requirements: Any = None,
    *,
    resource: str = "",
    purpose: str = "",
) -> Decision:
    """Screen the payer of an x402 payment payload (direction `inbound`).

    `requirements` defaults to the payload's own `accepted` block. The payee hook passes the
    server's matching requirements, which equal `accepted` field for field. A vendor
    middleware that screens before x402 runs must pass the same values (and the same
    `resource`), so the gate's short idempotency window dedups the two screens.
    """
    payer = payer_address(payment_payload)
    if not payer:
        raise ValueError("x402 payment payload has no authorization.from")
    req = requirements if requirements is not None else getattr(payment_payload, "accepted", None)
    if req is None:
        raise ValueError("no payment requirements to screen against")
    return await sk.screen(
        counterparty=payer,
        direction="inbound",
        amount=_amount(req),
        asset=req.asset,
        payment_chain_id=chain_id_from_network(req.network),
        source="x402",
        agent_id=agent_id,
        purpose=purpose,
        resource=resource,
    )


# ---------------------------------------------------------------------------- reasons


def abort_reason(decision: Decision) -> str:
    """`VERDICT|case_id|headline` for a HOLD or BLOCK decision."""
    headline = " ".join(str(decision.headline).split())  # one line, header-safe
    return f"{decision.verdict}|{decision.case_id}|{headline}"


def parse_abort_reason(reason: str) -> tuple[str, str | None, str]:
    """Split an abort reason into `(verdict, case_id, headline)`.

    "BLOCK|cs_…|headline"          -> ("BLOCK", "cs_…", "headline")
    "HOLD|unavailable|…"           -> ("HOLD", None, "…")  no case: the gate wasn't reached
    Also accepts `str(exc)` of the abort ("Payment aborted: …") and of the httpx wrapper.
    Anything that isn't a Sekisho reason parses as ("HOLD", None, text): fail closed.
    """
    text = str(reason or "").strip()
    marker = "Payment aborted: "
    if marker in text:
        text = text.rsplit(marker, 1)[1].strip()
    parts = text.split("|", 2)  # maxsplit: the headline may contain "|"
    verdict = parts[0].strip().upper()
    if verdict not in _VERDICTS:
        return "HOLD", None, text
    case = parts[1].strip() if len(parts) > 1 else ""
    headline = parts[2].strip() if len(parts) > 2 else ""
    return verdict, (case if case.startswith("cs_") else None), headline


def unwrap_payment_aborted(exc: BaseException | None) -> Any:
    """Return the x402 PaymentAbortedError if `exc` is one or wraps one, else None.

    `x402HttpxClient` raises `x402.http.clients.httpx.PaymentError("Failed to handle
    payment: …")` with the PaymentAbortedError as `__cause__`. This walks `__cause__`,
    `__context__` and exception groups, so it also works through other wrappers.
    """
    try:
        from x402.schemas import PaymentAbortedError
    except ImportError:  # pragma: no cover - without x402 there is nothing to unwrap
        return None
    seen: set[int] = set()
    queue: list[BaseException | None] = [exc]
    while queue:
        current = queue.pop(0)
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, PaymentAbortedError):
            return current
        queue.extend((current.__cause__, current.__context__))
        if isinstance(current, BaseExceptionGroup):
            queue.extend(current.exceptions)
    return None


# ---------------------------------------------------------------------------- helpers


def chain_id_from_network(network: str) -> int:
    """`eip155:84532` -> 84532. Raises ValueError for anything else (the hooks then HOLD)."""
    value = str(network)
    if value.startswith("eip155:"):
        return int(value.split(":", 1)[1])
    if value in _V1_CHAIN_IDS:
        return _V1_CHAIN_IDS[value]
    raise ValueError(f"unsupported x402 network {value!r} (expected eip155:<chainId>)")


def payer_address(payment_payload: Any) -> str | None:
    """The payer in an x402 payload: EIP-3009 `authorization.from`, or Permit2's.

    Takes a PaymentPayload, its inner `payload` dict, or the decoded wire dict.
    """
    inner = getattr(payment_payload, "payload", payment_payload)
    if isinstance(inner, Mapping) and isinstance(inner.get("payload"), Mapping):
        inner = inner["payload"]  # the full wire dict
    if not isinstance(inner, Mapping):
        return None
    for key in ("authorization", "permit2Authorization"):
        auth = inner.get(key)
        if isinstance(auth, Mapping):
            payer = auth.get("from")
            if isinstance(payer, str) and payer:
                return payer
    return None


def resource_from_verify_context(ctx: Any) -> str:
    """The URL the payer asked for: the HTTP request URL, else the payload's resource."""
    request = getattr(getattr(ctx, "transport_context", None), "request", None)
    get_url = getattr(getattr(request, "adapter", None), "get_url", None)
    if callable(get_url):
        try:
            return str(get_url())
        except Exception:  # noqa: BLE001 - best effort, context only
            pass
    url = getattr(getattr(getattr(ctx, "payment_payload", None), "resource", None), "url", None)
    return str(url) if url else ""


def _amount(req: Any) -> str:
    getter = getattr(req, "get_amount", None)  # v2 `amount`, v1 `max_amount_required`
    return str(getter() if callable(getter) else req.amount)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _failure_reason(exc: BaseException) -> str:
    if isinstance(exc, SekishoUnavailable):
        return f"HOLD|unavailable|{_UNAVAILABLE_HEADLINE}"
    return f"HOLD|unavailable|Screening failed ({type(exc).__name__}), failing closed"
