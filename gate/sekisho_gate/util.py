"""Small shared helpers: ids, times, hashes, amounts and explorer links."""

from __future__ import annotations

import math
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from eth_utils import keccak, to_checksum_address

# ---------- case ids (ULID, monotonic within one process) ----------

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ulid_lock = threading.Lock()
_ulid_last_ms = -1
_ulid_last_rand = 0


def new_ulid() -> str:
    """26-char Crockford base32 ULID. Ids made in the same millisecond still sort in
    creation order (the random part is incremented), so case ids sort newest-last."""
    global _ulid_last_ms, _ulid_last_rand
    with _ulid_lock:
        ms = int(time.time() * 1000)
        if ms <= _ulid_last_ms:
            ms = _ulid_last_ms
            rand = (_ulid_last_rand + 1) & ((1 << 80) - 1)
        else:
            rand = int.from_bytes(os.urandom(10), "big")
        _ulid_last_ms, _ulid_last_rand = ms, rand
    value = (ms << 80) | rand
    return "".join(_CROCKFORD[(value >> (5 * i)) & 31] for i in reversed(range(26)))


def new_case_id() -> str:
    return "cs_" + new_ulid()


def case_id_b32(case_id: str) -> str:
    """keccak(text=case_id): the bytes32 caseId used onchain."""
    return "0x" + keccak(text=case_id).hex()


def keccak_hex(data: bytes) -> str:
    return "0x" + keccak(data).hex()


def note_hash(note: str) -> str:
    """Officer note hash for overrideVerdict (PRD 9.11): keccak(text=note)."""
    return "0x" + keccak(text=note).hex()


# ---------- times ----------


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(ts: float | datetime | None = None) -> str:
    """ISO 8601 UTC with a Z suffix, second precision (docs/api.md conventions)."""
    if ts is None:
        dt = utcnow()
    elif isinstance(ts, datetime):
        dt = ts.astimezone(timezone.utc)
    else:
        dt = datetime.fromtimestamp(ts, timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- hex, addresses, integers ----------


def norm_hex32(value: Any) -> str | None:
    """Normalise a bytes32 / tx hash to 0x + 64 lowercase hex, or None."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        value = "0x" + bytes(value).hex()
    text = str(value).strip().lower()
    if not text.startswith("0x"):
        text = "0x" + text
    body = text[2:]
    if len(body) != 64 or any(c not in "0123456789abcdef" for c in body):
        return None
    return text


def checksum_or_none(value: Any) -> str | None:
    try:
        return to_checksum_address(str(value))
    except Exception:
        return None


def json_int(value: Any) -> Any:
    """Integers as JSON numbers when they fit in 2^53, otherwise decimal strings
    (docs/api.md ChainEvent.inputs). Non-integers pass through unchanged."""
    try:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            n = int(value, 0)
        elif isinstance(value, int):
            n = value
        else:
            return value
    except (TypeError, ValueError):
        return value
    return n if abs(n) < 2**53 else str(n)


def finite_or_none(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ---------- amounts ----------

USDC_DECIMALS = 6

# Known USDC deployments (6 decimals), including read-only mainnet contexts.
KNOWN_USDC = {
    (84532, "0x036CbD53842c5426634e7929541eC2318f3dCF7e"),  # Base Sepolia (payments)
    (8453, "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"),  # Base
    (1, "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),  # Ethereum
}

# Token scan target for a payment asset (PRD 9.2): the mainnet equivalent.
MAINNET_TOKEN_EQUIVALENT = {
    (84532, "0x036CbD53842c5426634e7929541eC2318f3dCF7e"): (
        8453,
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    ),
}
MAINNET_CHAIN_IDS = {1, 8453}


def is_known_usdc(chain_id: int, asset: str, extra_usdc: str | None = None) -> bool:
    asset_cs = checksum_or_none(asset)
    if asset_cs is None:
        return False
    return (chain_id, asset_cs) in KNOWN_USDC


def validate_payment_asset(chain_id: int, asset: str, configured_usdc: str) -> None:
    """The hackathon gate authorizes canonical Base Sepolia USDC payments only."""
    canonical = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    if (chain_id != 84532 or checksum_or_none(asset) != canonical
            or checksum_or_none(configured_usdc) != canonical):
        raise ValueError("Only canonical Base Sepolia USDC payments are supported")


def amount_to_usd(amount: str, chain_id: int, asset: str, extra_usdc: str | None = None) -> float:
    """Atomic canonical USDC amount -> USD; reject unknown valuations."""
    if not is_known_usdc(chain_id, asset, extra_usdc):
        raise ValueError("Unknown payment asset valuation")
    return round(int(amount) / 10**USDC_DECIMALS, 6)


def token_scan_target(chain_id: int, asset: str) -> tuple[int, str] | None:
    """(mainnet chain id, token address) to scan for a payment asset, or None."""
    asset_cs = checksum_or_none(asset)
    if asset_cs is None:
        return None
    if (chain_id, asset_cs) in MAINNET_TOKEN_EQUIVALENT:
        return MAINNET_TOKEN_EQUIVALENT[(chain_id, asset_cs)]
    if chain_id in MAINNET_CHAIN_IDS:
        return chain_id, asset_cs
    return None


def explorer_tx_url(explorer_url: str, tx_hash: str | None) -> str | None:
    if not tx_hash:
        return None
    return f"{explorer_url.rstrip('/')}/tx/{tx_hash}"


def short_addr(address: str) -> str:
    return f"{address[:6]}…{address[-4:]}" if address and len(address) > 12 else address
