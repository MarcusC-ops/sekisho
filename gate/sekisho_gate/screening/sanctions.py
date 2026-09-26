"""Chainalysis sanctions oracle over JSON-RPC `eth_call` (PRD 9.4).

`isSanctioned(address)` on Ethereum and Base mainnet, both chains in parallel. A chain
that fails gives None for that chain and makes the check status "error"; the policy
still BLOCKs if any chain says true. Keyless, free, no Intercepta quota: the tracer
uses `check_many` on every sender it looks at (one JSON-RPC batch per chain).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from typing import Any

import httpx
from eth_utils import is_address, keccak, to_checksum_address

from .types import CheckOutcome

NAME = "sanctions.oracle"

ORACLES = {
    1: "0x40C57923924B5c5c5455c48D93317139ADDaC8fb",  # Ethereum mainnet
    8453: "0x3A91A31cB3dC49b4db9Ce721F50a9D076c8D739B",  # Base mainnet
}
CHAIN_NAMES = {1: "Ethereum", 8453: "Base"}
SELECTOR = "0x" + keccak(text="isSanctioned(address)")[:4].hex()  # 0xdf592f7d
SELF_TEST_ADDRESS = "0x098B716B8Aaf21512996dC57EB0615e2383E2f96"  # Ronin Bridge exploiter (OFAC)

BATCH_SIZE = 25
_RETRYABLE = {429, 500, 502, 503, 504}


def calldata(address: str) -> str:
    return SELECTOR + address.lower().removeprefix("0x").rjust(64, "0")


def decode_bool(result: Any) -> bool | None:
    """An ABI-encoded bool (0x + 64 hex) -> bool; anything else -> None."""
    if not isinstance(result, str) or not result.startswith("0x") or len(result) != 66:
        return None
    try:
        value = int(result, 16)
    except ValueError:
        return None
    return value != 0 if value in (0, 1) else None


def _short(address: str) -> str:
    return f"{address[:6]}…{address[-4:]}"


class SanctionsOracle:
    def __init__(self, settings, http: httpx.AsyncClient | None = None, *, budget_s: float = 1.9) -> None:
        self.settings = settings
        self.rpc_urls = {1: settings.eth_mainnet_rpc_url, 8453: settings.base_mainnet_rpc_url}
        self.budget_s = budget_s  # stays inside the pipeline's 2 s per-check timeout
        self._own_http = http is None
        self._http = http or httpx.AsyncClient()

    # ---------- public ----------

    async def check(self, address: str) -> CheckOutcome:
        t0 = time.monotonic()
        if not isinstance(address, str) or not is_address(address):
            msg = f"not a valid address: {address!r}"
            return CheckOutcome(name=NAME, status="error", latency_ms=0, summary=msg, error=msg,
                                data={str(c): None for c in ORACLES})
        deadline = t0 + self.budget_s
        chains = list(ORACLES)
        results = await asyncio.gather(*(self._single(c, address, deadline) for c in chains))

        data: dict[str, bool | None] = {}
        raw: dict[str, Any] = {}
        errors: list[str] = []
        for chain_id, (value, body, err) in zip(chains, results):
            data[str(chain_id)] = value
            raw[str(chain_id)] = body
            if value is None:
                errors.append(f"{CHAIN_NAMES[chain_id]} ({chain_id}): {err or 'no answer'}")

        hits = [c for c in chains if data[str(c)] is True]
        if hits:
            summary = "sanctioned on " + " and ".join(str(c) for c in hits)
        elif not errors:
            summary = "not sanctioned (" + ", ".join(str(c) for c in chains) + ")"
        else:
            summary = "no sanctions hit"
        if errors:
            summary += "; failed: " + "; ".join(errors)
        return CheckOutcome(
            name=NAME,
            status="error" if errors else "ok",
            latency_ms=int((time.monotonic() - t0) * 1000),
            summary=summary,
            error="; ".join(errors) or None,
            data=data,
            raw=raw,
        )

    async def check_many(
        self, addresses: Iterable[str], chains: Iterable[int] = (1, 8453), *, budget_s: float | None = None
    ) -> dict[str, dict[str, bool | None]]:
        """{checksum address: {"1": bool | None, "8453": bool | None}} for many
        addresses, one JSON-RPC batch per chain (chunks of 25). Failed lookups are None."""
        unique = []
        for a in addresses:
            if isinstance(a, str) and is_address(a):
                cs = to_checksum_address(a)
                if cs not in unique:
                    unique.append(cs)
        chain_list = [c for c in chains if c in ORACLES]
        out = {a: {str(c): None for c in chain_list} for a in unique}
        if not unique:
            return out
        deadline = time.monotonic() + (budget_s if budget_s is not None else self.budget_s)
        jobs = []
        for c in chain_list:
            for i in range(0, len(unique), BATCH_SIZE):
                jobs.append((c, unique[i : i + BATCH_SIZE]))
        results = await asyncio.gather(*(self._batch(c, chunk, deadline) for c, chunk in jobs))
        for (c, chunk), values in zip(jobs, results):
            for a, v in zip(chunk, values):
                out[a][str(c)] = v
        return out

    async def self_test(self) -> tuple[bool, str]:
        """isSanctioned(0x098B…2F96) on Ethereum must be true (PRD 9.4)."""
        outcome = await self.check(SELF_TEST_ADDRESS)
        eth = (outcome.data or {}).get("1")
        if eth is True:
            hits = [c for c, v in (outcome.data or {}).items() if v is True]
            return True, f"{_short(SELF_TEST_ADDRESS)} sanctioned on {' and '.join(hits)}"
        if eth is False:
            return False, (
                f"oracle returned false for {_short(SELF_TEST_ADDRESS)} on Ethereum: "
                "the oracle address or the sanctions list may have changed"
            )
        return False, f"Ethereum oracle call failed: {outcome.error}"

    async def aclose(self) -> None:
        if self._own_http:
            await self._http.aclose()

    # ---------- internals ----------

    def _payload(self, chain_id: int, address: str, req_id: int) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "eth_call",
            "params": [{"to": ORACLES[chain_id], "data": calldata(address)}, "latest"],
        }

    async def _post(self, chain_id: int, payload: Any, deadline: float) -> tuple[Any, str | None]:
        """POST with one retry on 429/5xx/transport errors while time remains.
        Returns (parsed JSON body, error)."""
        url = self.rpc_urls[chain_id]
        error = "no attempt"
        for attempt in range(2):
            remaining = deadline - time.monotonic()
            if remaining <= 0.05:
                return None, error if attempt else "time budget exhausted"
            try:
                async with asyncio.timeout(remaining):  # whole-request cap (httpx's is per phase)
                    resp = await self._http.post(url, json=payload, timeout=remaining)
            except (httpx.TimeoutException, TimeoutError):
                return None, f"timed out after {self.budget_s:g} s"
            except httpx.HTTPError as exc:
                error = f"request failed: {type(exc).__name__}"
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json(), None
                    except ValueError:
                        return None, "non-JSON response"
                error = f"HTTP {resp.status_code}"
                if resp.status_code not in _RETRYABLE:
                    return None, error
            if deadline - time.monotonic() < 0.4:
                break
            await asyncio.sleep(0.15)
        return None, error

    async def _single(self, chain_id: int, address: str, deadline: float) -> tuple[bool | None, Any, str | None]:
        body, err = await self._post(chain_id, self._payload(chain_id, address, 1), deadline)
        if body is None:
            return None, None, err
        if not isinstance(body, dict):
            return None, body, "unexpected JSON-RPC response"
        if body.get("error"):
            e = body["error"]
            return None, body, f"RPC error: {e.get('message') if isinstance(e, dict) else e}"
        value = decode_bool(body.get("result"))
        return value, body, None if value is not None else f"unexpected result {body.get('result')!r}"

    async def _batch(self, chain_id: int, addresses: list[str], deadline: float) -> list[bool | None]:
        payload = [self._payload(chain_id, a, i) for i, a in enumerate(addresses)]
        body, _ = await self._post(chain_id, payload, deadline)
        if not isinstance(body, list):
            # Provider refused the batch: fall back to single calls.
            singles = await asyncio.gather(*(self._single(chain_id, a, deadline) for a in addresses))
            return [v for v, _, _ in singles]
        by_id = {item.get("id"): item for item in body if isinstance(item, dict)}
        return [decode_bool((by_id.get(i) or {}).get("result")) for i in range(len(addresses))]
