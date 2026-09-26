"""S5 (PRD 10.4): a simulated spoofed payer, for the seller-side screening demo.

Fetches the 402 terms from vendor-clean and builds an x402 v2 payment whose
`authorization.from` is ROGUE_PAYER_ADDR, a flagged mainnet address. Nothing is signed:
the signature is random bytes, because we hold no key for that address. The script sends
the payment in the PAYMENT-SIGNATURE header and prints how the vendor answered.

The vendor has to refuse on screening, before verification. Even if it didn't, the
facilitator would reject the random signature, so no money can move either way.

Exit code: 0 if the vendor refused, 1 if it accepted, 2 if the run could not happen
(vendor unreachable, or no 402 from it).

    .venv/bin/python agents/rogue/spoofed_payer.py [--vendor http://localhost:4021] [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import secrets
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

LABEL = "Simulated spoofed payer"
PAID_PATH = "/v1/market-data"
DEFAULT_VENDOR = "http://localhost:4021"
HTTP_TIMEOUT_S = 30.0  # longer than the vendor's own gate timeout (10 s)
_SEKISHO_VERDICTS = ("ALLOW", "HOLD", "BLOCK")


class SpoofRunError(RuntimeError):
    """The spoof could not be attempted (vendor unreachable, or no x402 v2 402)."""


@dataclass
class SpoofResult:
    accepted: bool
    status_code: int
    refused_by: str = ""  # payer_gate | payee_hook | x402 | vendor ("" when accepted)
    verdict: str | None = None
    case_id: str | None = None
    reasons: list[str] = field(default_factory=list)
    detail: str = ""
    payer: str = ""
    vendor_url: str = ""

    @property
    def screened(self) -> bool:
        """True when the refusal came from Sekisho screening (the S5 expectation)."""
        return self.refused_by in ("payer_gate", "payee_hook")

    @property
    def exit_code(self) -> int:
        return 1 if self.accepted else 0

    def to_json(self) -> dict[str, Any]:
        return {"label": LABEL, **asdict(self), "screened": self.screened}


def build_spoofed_payment(
    payment_required: dict[str, Any], payer: str, *, now: int | None = None
) -> dict[str, Any]:
    """An x402 v2 PaymentPayload claiming to come from `payer`, with a random signature.

    `accepted` is the 402's `accepts[0]` verbatim. The vendor matches it field for field,
    so any change makes it answer "No matching payment requirements" before screening.
    """
    accepts = payment_required.get("accepts") or []
    if not accepts:
        raise SpoofRunError("the 402 lists no payment requirements (accepts is empty)")
    accepted = accepts[0]
    issued = int(time.time()) if now is None else now
    payment: dict[str, Any] = {
        "x402Version": 2,
        "accepted": accepted,
        "payload": {
            "signature": "0x" + secrets.token_hex(65),  # random: we hold no key for `payer`
            "authorization": {
                "from": payer,
                "to": accepted["payTo"],
                "value": accepted["amount"],
                "validAfter": "0",
                "validBefore": str(issued + int(accepted.get("maxTimeoutSeconds") or 300)),
                "nonce": "0x" + secrets.token_hex(32),
            },
        },
    }
    if payment_required.get("resource"):
        payment["resource"] = payment_required["resource"]  # the real x402 client echoes it too
    return payment


def encode_payment_header(payment: dict[str, Any]) -> str:
    """PAYMENT-SIGNATURE value: standard base64 of the JSON (not urlsafe), as x402 encodes it."""
    return base64.b64encode(json.dumps(payment, separators=(",", ":")).encode()).decode()


def decode_payment_required(header: str) -> dict[str, Any]:
    return json.loads(base64.b64decode(header))


def classify(response: httpx.Response) -> SpoofResult:
    """Work out who refused (or whether the vendor accepted) from the paid response."""
    status = response.status_code
    if 200 <= status < 300:
        return SpoofResult(accepted=True, status_code=status, detail=response.text[:300])
    body: Any = None
    try:
        body = response.json()
    except ValueError:
        pass
    if status == 403 and isinstance(body, dict) and body.get("error") == "payer_refused":
        return SpoofResult(
            accepted=False,
            status_code=status,
            refused_by="payer_gate",
            verdict=body.get("verdict"),
            case_id=body.get("case_id"),
            reasons=[str(r) for r in body.get("reasons") or []],
            detail=str(body.get("headline") or ""),
        )
    header = response.headers.get("PAYMENT-REQUIRED")
    if status == 402 and header:
        try:
            error = str(decode_payment_required(header).get("error") or "")
        except ValueError:
            error = ""
        parts = error.split("|", 2)
        if len(parts) == 3 and parts[0] in _SEKISHO_VERDICTS:
            case_id = parts[1] if parts[1].startswith("cs_") else None
            return SpoofResult(
                accepted=False, status_code=status, refused_by="payee_hook",
                verdict=parts[0], case_id=case_id, reasons=[parts[2]], detail=error,
            )
        return SpoofResult(accepted=False, status_code=status, refused_by="x402", detail=error)
    return SpoofResult(accepted=False, status_code=status, refused_by="vendor", detail=response.text[:300])


async def run(
    vendor_url: str,
    payer: str,
    pair: str = "ETH-JPY",
    *,
    http: httpx.AsyncClient | None = None,
    say: Callable[[str], None] | None = None,
) -> SpoofResult:
    """Fetch the 402, send the spoofed payment and classify the answer. Raises SpoofRunError."""
    out = say or (lambda line: print(f"[{LABEL}] {line}", flush=True))
    url = _market_data_url(vendor_url)
    client = http or httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)
    try:
        out(f"S5: a crafted x402 payment claiming to come from {payer}")
        out("We hold no key for that address, so the signature is random bytes. Nothing is signed.")
        try:
            first = await client.get(url, params={"pair": pair})
        except httpx.HTTPError as exc:
            raise SpoofRunError(f"vendor unreachable at {url}: {type(exc).__name__}: {exc}") from exc
        header = first.headers.get("PAYMENT-REQUIRED")
        if first.status_code != 402 or not header:
            raise SpoofRunError(f"expected a 402 with PAYMENT-REQUIRED from {url}, got HTTP {first.status_code}")
        payment_required = decode_payment_required(header)
        if payment_required.get("x402Version") != 2:
            raise SpoofRunError(f"expected x402 v2, got {payment_required.get('x402Version')!r}")
        payment = build_spoofed_payment(payment_required, payer)
        terms = payment["accepted"]
        out(f"GET {url}?pair={pair} -> 402: pay {_usdc(terms['amount'])} to {terms['payTo']} "
            f"on {terms['network']}")
        out(f"Sending PAYMENT-SIGNATURE with authorization.from = {payer}")
        try:
            paid = await client.get(url, params={"pair": pair},
                                    headers={"PAYMENT-SIGNATURE": encode_payment_header(payment)})
        except httpx.HTTPError as exc:
            raise SpoofRunError(f"vendor failed on the paid request: {type(exc).__name__}: {exc}") from exc
        result = classify(paid)
        result.payer, result.vendor_url = payer, url
        _report(result, out)
        return result
    finally:
        if http is None:
            await client.aclose()


def _report(result: SpoofResult, out: Callable[[str], None]) -> None:
    if result.accepted:
        out(f"ACCEPTED: HTTP {result.status_code}, the vendor served a spoofed payer. This must not happen.")
        return
    case = f", case {result.case_id}" if result.case_id else ""
    if result.refused_by == "payer_gate":
        out(f"REFUSED: HTTP 403 payer_refused. Sekisho verdict {result.verdict}{case}")
    elif result.refused_by == "payee_hook":
        out(f"REFUSED: HTTP 402 from the x402 before_verify hook. Sekisho verdict {result.verdict}{case}")
    else:
        out(f"REFUSED, but not by Sekisho screening: HTTP {result.status_code} {result.detail!r}")
        out("WARNING: the vendor should refuse on screening. Is the gate up and the payer flagged?")
        return
    for reason in result.reasons:
        out(f"  reason: {reason}")
    out("Refused before verification: the facilitator was never asked to verify or settle.")


def _market_data_url(vendor_url: str) -> str:
    base = vendor_url.rstrip("/")
    return base if urlsplit(base).path not in ("", "/") else base + PAID_PATH


def _usdc(atomic: Any) -> str:
    try:
        return f"{int(atomic) / 1_000_000:g} USDC ({atomic} atomic)"
    except (TypeError, ValueError):
        return f"{atomic} (atomic)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{LABEL} (S5): send a crafted x402 payment to a vendor")
    parser.add_argument("--vendor", default=DEFAULT_VENDOR, help=f"vendor base URL (default {DEFAULT_VENDOR})")
    parser.add_argument("--payer", default=None, help="address in authorization.from (default ROGUE_PAYER_ADDR)")
    parser.add_argument("--pair", default="ETH-JPY")
    parser.add_argument("--json", action="store_true", help="print one JSON result line instead of the log")
    args = parser.parse_args(argv)

    payer = args.payer
    if not payer:
        from sekisho_gate.config import get_settings

        payer = get_settings().rogue_payer_addr
    say = (lambda line: None) if args.json else None
    try:
        result = asyncio.run(run(args.vendor, payer, args.pair, say=say))
    except SpoofRunError as exc:
        if args.json:
            print(json.dumps({"label": LABEL, "error": str(exc)}))
        else:
            print(f"[{LABEL}] ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result.to_json()))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
