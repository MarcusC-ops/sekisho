"""Intercepta (web3antivirus) client (PRD 9.3).

Every public method returns a `CheckOutcome` and never raises for upstream failures.
`raw` is the response body exactly as received (parsed JSON, or the text if it is not
JSON). Trait descriptions are kept verbatim.

- Header `X-API-KEY`. An empty key is an immediate error with no HTTP call.
- 401/403 means a bad key: an error, never retried. No Intercepta call is retried: each
  retry costs quota and the direct scan has a 3 s budget.
- Missing/empty responses are errors. Only explicit, well-formed provider evidence
  can establish a zero-risk score; never synthesize clean wallet history.
- Every HTTP call is counted in the `quota` table before it is sent.
- Cache: 24 h, keyed by (endpoint, address). Only complete 200 responses are cached.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from eth_utils import is_address

from .cache import QUOTA_KEY, InterceptaCache
from .types import CheckOutcome

log = logging.getLogger(__name__)

QUICK_SCAN = "intercepta.quick_scan"
DEEP_SCAN = "intercepta.deep_scan"
IMPERSONATION = "intercepta.impersonation"
TOKEN = "intercepta.token"

PATHS = {
    "quick_scan": "/api/public/v2/extension/account/{address}/quick-scan",
    "deep_scan": "/api/public/v2/extension/account/{address}/toxic-score",
    "impersonation": "/api/public/v1/extension/poisoning-attack/check-address/{address}",
    "token": "/api/public/v2/extension/token-intelligence/token/{address}/risks",
}

TIMEOUT_QUICK_S = 3.0
TIMEOUT_DEEP_S = 5.0
TIMEOUT_OTHER_S = 3.0

FAULT_TIMEOUT = "intercepta_timeout"  # FAULT_INJECT value for demo scenario S6


def _num(value: Any) -> int | float | None:
    """A JSON number as int when integral, float otherwise; None if not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _parse_body(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


def _upstream_message(parsed: Any) -> str:
    """The human message from an Intercepta error body, e.g. the 403 `response` field."""
    if isinstance(parsed, dict):
        for key in ("response", "message", "error"):
            value = parsed.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(parsed, str):
        return parsed.strip()[:200]
    return ""


# ---------- response parsers: parsed JSON -> (data, summary) or ValueError ----------


def _parse_score(parsed: Any) -> tuple[dict, str]:
    if not isinstance(parsed, dict):
        raise ValueError("expected a JSON object")
    score = _num(parsed.get("toxicScore"))
    traits = parsed.get("traits")
    if score is None or not isinstance(traits, list):
        raise ValueError("missing toxicScore or traits")
    out = []
    for t in traits:
        if not isinstance(t, dict) or not isinstance(t.get("name"), str):
            continue
        out.append(
            {
                "name": t["name"],
                "risk": _num(t.get("risk")),
                "txsCount": _num(t.get("txsCount")),
                "description": t.get("description"),  # verbatim
            }
        )
    names = ", ".join(t["name"] for t in out)
    summary = f"toxicScore {score}, {len(out)} trait{'s' if len(out) != 1 else ''}"
    return {"toxicScore": score, "traits": out}, summary + (f": {names}" if names else "")


def _parse_impersonation(parsed: Any) -> tuple[dict, str]:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("isAddressPoisoned"), bool):
        raise ValueError("missing isAddressPoisoned")
    poisoned = parsed["isAddressPoisoned"]
    original = parsed.get("originalAddress") or None
    data = {"isAddressPoisoned": poisoned, "originalAddress": original}
    if poisoned:
        return data, f"poisoned lookalike of {original}" if original else "poisoned lookalike"
    return data, "not a poisoning lookalike"


def _parse_token(parsed: Any) -> tuple[dict, str]:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("action"), str):
        raise ValueError("missing action")
    detectors = []
    for d in parsed.get("detectors") or []:
        if isinstance(d, dict):
            detectors.append({"code": d.get("code"), "description": d.get("description")})
    data = {
        "riskScore": _num(parsed.get("riskScore")),
        "riskLevel": parsed.get("riskLevel"),
        "trust": parsed.get("trust"),
        "action": parsed["action"],
        "detectors": detectors,
    }
    summary = f"action {data['action']}, riskLevel {data['riskLevel']}, riskScore {data['riskScore']}"
    return data, summary


class InterceptaClient:
    def __init__(self, settings, http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._base = settings.intercepta_base_url.rstrip("/")
        self._key = settings.intercepta_api_key.get_secret_value().strip()
        self._own_http = http is None
        self._http = http or httpx.AsyncClient()
        self.cache = InterceptaCache(settings.db_path)
        self.last_http_status: int | None = None

    # ---------- public checks ----------

    async def quick_scan(self, address: str, *, live: bool = True) -> CheckOutcome:
        """Quick Scan the counterparty. `live=True` skips the cache read (the cache is
        still written); the direct scan is never skipped for quota."""
        return await self._call(
            QUICK_SCAN, "quick_scan", address, timeout_s=TIMEOUT_QUICK_S,
            read_cache=not live, respect_reserve=False, parse=_parse_score,
        )

    async def quick_scan_cached(self, address: str) -> CheckOutcome:
        """Quick Scan for a tracer funder: cache first, and `skipped` (no call) once the
        quota is at INTERCEPTA_RESERVE_FROM so the direct scans keep their budget."""
        return await self._call(
            QUICK_SCAN, "quick_scan", address, timeout_s=TIMEOUT_QUICK_S,
            read_cache=True, respect_reserve=True, parse=_parse_score,
        )

    async def deep_scan(self, address: str, *, live: bool = False) -> CheckOutcome:
        """Deep Scan (after a HOLD, for the officer). Cache first unless `live`."""
        return await self._call(
            DEEP_SCAN, "deep_scan", address, timeout_s=TIMEOUT_DEEP_S,
            read_cache=not live, respect_reserve=False, parse=_parse_score,
        )

    async def impersonation(self, address: str, *, live: bool = False) -> CheckOutcome:
        """Address-poisoning lookalike check. Cache first unless `live`."""
        return await self._call(
            IMPERSONATION, "impersonation", address, timeout_s=TIMEOUT_OTHER_S,
            read_cache=not live, respect_reserve=False, parse=_parse_impersonation,
        )

    async def token_scan(self, token_address: str, chain_id: int = 8453) -> CheckOutcome:
        """Scan Token on a mainnet chain. Cached 24 h per (chain, token)."""
        return await self._call(
            TOKEN, "token", token_address, timeout_s=TIMEOUT_OTHER_S,
            read_cache=True, respect_reserve=False, parse=_parse_token,
            params={"chainId": str(chain_id)}, cache_endpoint=f"token:{chain_id}",
        )

    # ---------- status ----------

    def quota_status(self) -> dict:
        used = self.cache.value(QUOTA_KEY)
        quota = int(self.settings.intercepta_quota)
        return {
            "used": used,
            "quota": quota,
            "remaining": max(0, quota - used),
            "warn_at": int(self.settings.intercepta_warn_at),
            "reserve_from": int(self.settings.intercepta_reserve_from),
        }

    def key_status(self) -> tuple[bool, str]:
        """From config and the last HTTP status seen. Makes no API call."""
        q = self.quota_status()
        usage = f"{q['used']}/{q['quota']} used"
        if not self._key:
            return False, "INTERCEPTA_API_KEY is not set"
        if self.last_http_status in (401, 403):
            return False, f"invalid Intercepta API key (HTTP {self.last_http_status}), {usage}"
        if self.last_http_status is None:
            return True, f"key set, not yet used this run, {usage}"
        if self.last_http_status == 200:
            return True, f"key valid, {usage}"
        return True, f"key set, last call HTTP {self.last_http_status}, {usage}"

    async def aclose(self) -> None:
        if self._own_http:
            await self._http.aclose()

    # ---------- internals ----------

    async def _call(
        self,
        name: str,
        kind: str,
        address: str,
        *,
        timeout_s: float,
        read_cache: bool,
        respect_reserve: bool,
        parse: Callable[[Any], tuple[dict, str]],
        params: dict | None = None,
        cache_endpoint: str | None = None,
    ) -> CheckOutcome:
        t0 = time.monotonic()

        def ms() -> int:
            return int((time.monotonic() - t0) * 1000)

        def fail(error: str, *, live: bool | None, raw: Any = None) -> CheckOutcome:
            return CheckOutcome(
                name=name, status="error", live=live, latency_ms=ms(),
                summary=error, error=error, raw=raw,
            )

        if not isinstance(address, str) or not is_address(address):
            return fail(f"not a valid address: {address!r}", live=None)
        addr = address.lower()
        endpoint = cache_endpoint or kind

        if read_cache:
            cached = self.cache.get(endpoint, addr)
            if cached is not None:
                parsed = _parse_body(cached)
                try:
                    data, summary = parse(parsed)
                except ValueError:
                    pass  # unreadable cache row: fall through to a live call
                else:
                    return CheckOutcome(
                        name=name, status="ok", live=False, latency_ms=ms(),
                        summary=summary + " (cached)", data=data, raw=parsed,
                    )

        if not self._key:
            return fail("INTERCEPTA_API_KEY is not set", live=None)
        if self.settings.fault_inject.strip().lower() == FAULT_TIMEOUT:
            return fail(f"timed out (FAULT_INJECT={FAULT_TIMEOUT})", live=None)
        if respect_reserve:
            used = self.cache.value(QUOTA_KEY)
            if used >= self.settings.intercepta_reserve_from:
                msg = (
                    f"skipped: quota reserve ({used} used >= "
                    f"INTERCEPTA_RESERVE_FROM {self.settings.intercepta_reserve_from})"
                )
                return CheckOutcome(name=name, status="skipped", live=None, latency_ms=ms(), summary=msg)

        used = self.cache.incr(QUOTA_KEY)
        if used >= self.settings.intercepta_warn_at:
            log.warning(
                "Intercepta quota: %d of %d requests used", used, self.settings.intercepta_quota,
                extra={"intercepta_used": used},
            )

        url = self._base + PATHS[kind].format(address=addr)
        try:
            async with asyncio.timeout(timeout_s):  # whole-request cap (httpx's is per phase)
                resp = await self._http.get(
                    url,
                    params=params,
                    headers={"X-API-KEY": self._key, "Accept": "application/json"},
                    timeout=timeout_s,
                )
        except (httpx.TimeoutException, TimeoutError):
            return fail(f"timed out after {timeout_s:g} s", live=True)
        except httpx.HTTPError as exc:
            return fail(f"request failed: {type(exc).__name__}", live=True)

        self.last_http_status = resp.status_code
        text = resp.text
        parsed = _parse_body(text)
        status = resp.status_code

        if status in (401, 403):
            upstream = _upstream_message(parsed)
            msg = f"invalid Intercepta API key (HTTP {status})" + (f": {upstream}" if upstream else "")
            log.error(msg)
            return fail(msg, live=True, raw=parsed)

        if status == 404 and "cannot get" in text.lower():
            return fail("Intercepta endpoint not found (HTTP 404)", live=True, raw=parsed)

        if status != 200:
            upstream = _upstream_message(parsed)
            log.warning("Intercepta %s HTTP %d: %s", kind, status, text[:500])
            return fail(f"HTTP {status}" + (f": {upstream}" if upstream else ""), live=True, raw=parsed)

        try:
            data, summary = parse(parsed)
        except ValueError as exc:
            return fail(f"unexpected response: {exc}", live=True, raw=parsed)

        self.cache.put(endpoint, addr, text)
        return CheckOutcome(
            name=name, status="ok", live=True, latency_ms=ms(), summary=summary, data=data, raw=parsed,
        )
