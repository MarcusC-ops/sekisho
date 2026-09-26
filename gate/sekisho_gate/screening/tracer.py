"""Source-of-funds tracer (PRD 9.5): where did this wallet's money come from, and how
much of it came from flagged sources?

Data: Blockscout REST v2, first page (50 items) of three inbound feeds per chain:
ERC-20 transfers, native transactions (sorted by value, largest first) and internal
transactions (mixer withdrawals arrive as internal transactions). The PRO API
(`api.blockscout.com/{chainId}/...`) is used when BLOCKSCOUT_API_KEY is set; otherwise
the keyless public hosts, which are for development only.

Algorithm (hop 1 P0, hop 2 P1), parameters from the policy YAML `trace` section:
1. Normalise inbound transfers to {from, chain_id, symbol, amount, usd}: canonical
   stablecoins at face value, ETH and canonical WETH x ETH_USD_PRICE, anything else $0
   (counted, not weighted). Drop zero-value, failed, self and scam-token transfers.
2. Group by sender and take the top `top_k_hop1` by usd (tie-break tx_count). Senders
   under $1 (dust, e.g. address poisoning) or with only unpriced tokens are counted in
   the total but not ranked, at either hop.
3. Flag each: sanctions oracle; cached Intercepta Quick Scan (hard-block or hold trait,
   or toxicScore >= hold_score); Blockscout is_scam; label keywords from the policy.
4. Hop 2: for the top `top_k_hop2` unflagged hop-1 senders, trace their Ethereum
   inbound the same way and flag the top senders with the oracle and labels only.
5. taint_usd = sum(flagged hop-1 usd) + hop2_weight x sum(usd of hop-1 senders with a
   flagged hop-2 sender); taint_pct = 100 x taint_usd / all traced inbound usd.

Everything fits in `budget_s` (5.5 s, inside the pipeline's 6 s timeout). If hop 2 runs
out of time the hop-1 result is returned with a note.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

import httpx
from eth_utils import is_address, to_checksum_address

from .types import CheckOutcome

log = logging.getLogger(__name__)

NAME = "trace.source_of_funds"

KEYLESS_HOSTS = {1: "https://eth.blockscout.com", 8453: "https://base.blockscout.com"}
CHAIN_NAMES = {1: "Ethereum", 8453: "Base"}
FEEDS = ("erc20", "native", "internal")
FEED_PATHS = {
    "erc20": "/api/v2/addresses/{address}/token-transfers",
    "native": "/api/v2/addresses/{address}/transactions",
    "internal": "/api/v2/addresses/{address}/internal-transactions",
}
FEED_PARAMS = {
    "erc20": {"type": "ERC-20", "filter": "to"},
    "native": {"filter": "to", "sort": "value", "order": "desc"},
    "internal": {"filter": "to"},
}
FEED_LABELS = {"erc20": "ERC-20 transfers", "native": "native transactions", "internal": "internal transactions"}

# Tokens valued by the tracer, by (chain, lowercased contract address). A token that
# only *claims* a stablecoin or WETH symbol is valued at $0, so fake tokens cannot
# inflate (or dilute) the traced value.
CANONICAL_TOKENS: dict[tuple[int, str], str] = {
    (1, "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"): "USDC",
    (1, "0xdac17f958d2ee523a2206206994597c13d831ec7"): "USDT",
    (1, "0x6b175474e89094c44da98b954eedeac495271d0f"): "DAI",
    (1, "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"): "WETH",
    (8453, "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"): "USDC",
    (8453, "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca"): "USDbC",
    (8453, "0x50c5725949a6f0c72e6c4a641f24049a917db0cb"): "DAI",
    (8453, "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2"): "USDT",
    (8453, "0x4200000000000000000000000000000000000006"): "WETH",
}

DEFAULT_TRACE = {
    "chains": [1, 8453],
    "inbound_page_size": 50,
    "top_k_hop1": 5,
    "top_k_hop2": 3,
    "hop2_weight": 0.5,
    "label_keywords": ["tornado", "mixer", "exploit", "hack", "phish", "lazarus", "drainer"],
    "stablecoins": ["USDC", "USDT", "DAI", "USDbC"],
}
DEFAULT_HARD_BLOCK = ["sanction_address", "known_scammer", "initiator_scam_transactions", "blacklist"]
DEFAULT_HOLD = [
    "sanction_address_communication", "mixer_transfers", "non_kyc_transfers",
    "fake_phishing_contract_communication", "attack_money_target", "rug_pull",
    "rug_pull_trader", "suspicious_deployer", "suspicious_dex_pair_deployer",
]

BUDGET_S = 5.5
# A sender must have sent at least this much priced value to rank as a funding source.
# Address-poisoning and phishing dust (e.g. 1e-7 WETH from a "Phish / Hack" address)
# would otherwise be flagged, and at hop 2 one dust sender taints the whole via.
MIN_SENDER_USD = 1.0
PER_CALL_TIMEOUT_S = 4.0
HOP1_RESERVE_S = 1.2  # time kept back after the hop-1 fetch for flagging
HOP2_MIN_S = 1.2  # do not start hop 2 with less than this left
_RETRYABLE = {429, 500, 502, 503, 504}


class _Deadline:
    def __init__(self, seconds: float) -> None:
        self.end = time.monotonic() + seconds

    def remaining(self) -> float:
        return self.end - time.monotonic()


class _RateLimiter:
    """Token bucket: `rate` requests per second with a burst of `burst`. Blockscout's
    free tier allows 5 RPS; a semaphore alone caps concurrency, not rate."""

    def __init__(self, rate: float = 4.0, burst: int = 4) -> None:
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, max_wait: float) -> bool:
        async with self._lock:
            now = time.monotonic()
            self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            wait = 0.0 if self.tokens >= 1 else (1 - self.tokens) / self.rate
            if wait > max_wait:
                return False
            if wait:
                await asyncio.sleep(wait)
                self.tokens = min(self.burst, self.tokens + wait * self.rate)
                self.updated = time.monotonic()
            self.tokens -= 1
            return True


@dataclass
class _Feed:
    hop: int
    chain_id: int
    feed: str
    address: str
    url: str  # without the API key
    status: int | None = None
    items: list = field(default_factory=list)
    next_page: bool = False
    error: str | None = None

    def source(self) -> dict:
        return {
            "hop": self.hop, "chain_id": self.chain_id, "feed": self.feed, "address": self.address,
            "url": self.url, "status": self.status, "items": len(self.items),
            "next_page": self.next_page, "error": self.error,
        }


@dataclass
class _Sender:
    address: str
    chain_id: int
    usd: float = 0.0
    tx_count: int = 0
    labels: list[str] = field(default_factory=list)
    match: list[str] = field(default_factory=list)
    is_scam: bool = False
    flags: list[str] = field(default_factory=list)
    sanctioned: bool = False
    intercepta: dict | None = None

    @property
    def display(self) -> str:
        return self.labels[0] if self.labels else _short(self.address)


def _short(address: str) -> str:
    return f"{address[:6]}…{address[-4:]}"


def _money(usd: float) -> str:
    return f"${usd:,.0f}" if abs(usd) >= 100 else f"${usd:,.2f}"


def _n(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _chain_name(chain_id: int) -> str:
    return CHAIN_NAMES.get(chain_id, f"chain {chain_id}")


def _int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def sender_info(addr: dict | None) -> tuple[list[str], list[str], bool]:
    """(display labels, text to match keywords against, is_scam) for a Blockscout
    address object. Labels live in `metadata.tags[]`; `public_tags` is usually empty."""
    addr = addr or {}
    tags = [t for t in ((addr.get("metadata") or {}).get("tags") or []) if isinstance(t, dict)]
    shown = [t for t in tags if t.get("tagType") != "note"]
    labels: list[str] = []
    labels += [t.get("name") for t in shown if t.get("tagType") == "name"]
    labels += [addr.get("name"), addr.get("ens_domain_name")]
    for pt in addr.get("public_tags") or []:
        labels.append((pt.get("display_name") or pt.get("label")) if isinstance(pt, dict) else pt)
    labels += [t.get("name") for t in shown if t.get("tagType") != "name"]
    labels = list(dict.fromkeys(x for x in labels if isinstance(x, str) and x.strip()))
    match = list(labels)
    for t in tags:
        if t.get("tagType") != "note" and isinstance(t.get("slug"), str):
            match.append(t["slug"])
        info = (t.get("meta") or {}).get("info")
        if isinstance(info, list):
            match += [x for x in info if isinstance(x, str)]
    is_scam = bool(addr.get("is_scam")) or addr.get("reputation") == "scam"
    return labels, match, is_scam


def label_flags(match: list[str], is_scam: bool, keywords: list[str]) -> list[str]:
    flags = ["label:is_scam"] if is_scam else []
    text = [m.lower() for m in match]
    for kw in keywords:
        k = str(kw).lower()
        if k and any(k in m for m in text):
            flags.append(f"label:{k}")
    return flags


class Tracer:
    def __init__(
        self,
        settings,
        oracle,
        intercepta,
        policy_cfg: dict,
        http: httpx.AsyncClient | None = None,
        *,
        budget_s: float = BUDGET_S,
        rate_limit_rps: float = 4.0,
        min_sender_usd: float = MIN_SENDER_USD,
    ) -> None:
        self.settings = settings
        self.oracle = oracle
        self.intercepta = intercepta
        self.budget_s = budget_s
        self.min_usd = min_sender_usd
        self._own_http = http is None
        self._http = http or httpx.AsyncClient()
        self._key = settings.blockscout_api_key.get_secret_value().strip()
        self._base = settings.blockscout_base.rstrip("/")
        self._sem = asyncio.Semaphore(4)
        self._limiter = _RateLimiter(rate=rate_limit_rps, burst=4)

        cfg = policy_cfg or {}
        full = cfg if ("trace" in cfg or "thresholds" in cfg) else {}
        trace = full.get("trace", {}) if full else cfg
        self.cfg = {**DEFAULT_TRACE, **(trace or {})}
        self.chains = [int(c) for c in self.cfg["chains"]]
        self.page_size = int(self.cfg["inbound_page_size"])
        self.k1 = int(self.cfg["top_k_hop1"])
        self.k2 = int(self.cfg["top_k_hop2"])
        self.w2 = float(self.cfg["hop2_weight"])
        self.keywords = [str(k).lower() for k in self.cfg["label_keywords"]]
        self.stablecoins = set(self.cfg["stablecoins"])
        self.hold_score = float((full.get("thresholds") or {}).get("hold_score", 40))
        self.risky_traits = set(full.get("hard_block_traits") or DEFAULT_HARD_BLOCK) | set(
            full.get("hold_traits") or DEFAULT_HOLD
        )
        self.eth_usd = float(settings.eth_usd_price)

    async def aclose(self) -> None:
        if self._own_http:
            await self._http.aclose()

    # ---------- public ----------

    async def trace(self, address: str) -> CheckOutcome:
        t0 = time.monotonic()
        try:
            async with asyncio.timeout(self.budget_s + 0.3):  # safety net; phases have their own limits
                return await self._trace(address, t0)
        except TimeoutError:
            msg = f"trace exceeded its {self.budget_s:g} s budget"
            return CheckOutcome(name=NAME, status="error", latency_ms=int((time.monotonic() - t0) * 1000),
                                summary=msg, error=msg)
        except Exception as exc:  # a bug must not take the pipeline down: report an error
            log.exception("trace crashed")
            msg = f"trace failed: {type(exc).__name__}: {exc}"
            return CheckOutcome(
                name=NAME, status="error", latency_ms=int((time.monotonic() - t0) * 1000),
                summary=msg[:300], error=msg[:500],
            )

    async def _trace(self, address: str, t0: float) -> CheckOutcome:
        dl = _Deadline(self.budget_s)
        if not isinstance(address, str) or not is_address(address):
            msg = f"not a valid address: {address!r}"
            return CheckOutcome(name=NAME, status="error", latency_ms=0, summary=msg, error=msg)
        target = to_checksum_address(address)
        notes = [
            f"First page only: up to {self.page_size} inbound items per feed (ERC-20, native, "
            "internal) per chain; native transactions are the largest by value",
            f"ETH and WETH valued at ETH_USD_PRICE (${self.eth_usd:,.0f}), a demo approximation; "
            "stablecoins at face value; other tokens counted at $0",
            "raw holds the normalised transfers and source URLs, not the full Blockscout pages",
        ]
        if not self._key:
            notes.append("Blockscout keyless public hosts (development only; BLOCKSCOUT_API_KEY not set)")

        # Hop 1: fetch every feed on every chain.
        feeds = await asyncio.gather(
            *(self._fetch(1, c, f, target, dl, reserve=HOP1_RESERVE_S) for c in self.chains for f in FEEDS)
        )
        failed = [f for f in feeds if f.error]
        for f in failed:
            notes.append(f"{_chain_name(f.chain_id)} {FEED_LABELS[f.feed]} not traced: {f.error}")
        if len(failed) == len(feeds):
            msg = "no Blockscout data: " + "; ".join(
                f"{_chain_name(f.chain_id)} {f.feed}: {f.error}" for f in failed
            )
            return CheckOutcome(
                name=NAME, status="error", latency_ms=int((time.monotonic() - t0) * 1000),
                summary=msg[:300], error=msg[:500], raw={"sources": [f.source() for f in feeds]},
            )

        drops: Counter = Counter()
        transfers, senders = self._normalise(feeds, target, drops)
        inbound = sum(t["usd"] for t in transfers)
        ranked = sorted(
            (s for s in senders.values() if s.usd >= self.min_usd),
            key=lambda s: (-s.usd, -s.tx_count, s.address, s.chain_id),
        )
        top = ranked[: self.k1]
        unpriced = sum(1 for s in senders.values() if s.usd <= 0)
        dust = sum(1 for s in senders.values() if 0 < s.usd < self.min_usd)
        if unpriced:
            notes.append(f"{_n(unpriced, 'sender')} with only unpriced transfers counted but not ranked")
        if dust:
            notes.append(f"{_n(dust, 'sender')} under {_money(self.min_usd)} (dust) counted but not ranked")
        self._drop_notes(drops, notes)

        await self._flag_hop1(top, dl, notes)

        # Hop 2 (P1).
        hop2: list[dict] = []
        hop2_transfers: list[dict] = []
        hop2_feeds: list[_Feed] = []
        candidates = [s for s in top if not s.flags][: self.k2]
        if not self.settings.trace_enable_hop2:
            notes.append("hop 2 off (TRACE_ENABLE_HOP2=false)")
        elif self.k2 <= 0:
            notes.append("hop 2 off (policy top_k_hop2 = 0)")
        elif candidates:
            if dl.remaining() < HOP2_MIN_S:
                notes.append("hop 2 skipped: time budget used by hop 1; hop-1 result only")
            else:
                try:
                    hop2, hop2_transfers, hop2_feeds = await asyncio.wait_for(
                        self._hop2(candidates, target, dl, notes), timeout=max(0.1, dl.remaining() - 0.1)
                    )
                except asyncio.TimeoutError:
                    notes.append("hop 2 timed out; hop-1 result only")
                    hop2, hop2_transfers, hop2_feeds = [], [], []

        # Taint.
        flagged_vias = {e["via"] for e in hop2 if e["flags"]}
        flagged_usd = sum(s.usd for s in top if s.flags)
        via_usd = sum(s.usd for s in top if not s.flags and s.address in flagged_vias)
        taint_usd = flagged_usd + self.w2 * via_usd
        taint_pct = round(100.0 * taint_usd / inbound, 2) if inbound > 0 else 0.0
        if inbound <= 0:
            notes.append("no priced inbound value traced")

        paths = self._paths(top, hop2)
        truncated = any(f.next_page for f in (*feeds, *hop2_feeds))
        data = {
            "chains": self.chains,
            "inbound_usd_traced": round(inbound, 2),
            "hop1": [self._hop1_entry(s, inbound) for s in top],
            "hop2": hop2,
            "taint_pct": taint_pct,
            "taint_usd": round(taint_usd, 2),
            "paths": paths,
            "truncated": truncated,
            "notes": notes,
        }
        raw = {
            "note": "Normalised inbound transfers and Blockscout source URLs; full Blockscout "
            "pages are not stored (too large to hash into every report)",
            "sources": [f.source() for f in (*feeds, *hop2_feeds)],
            "hop1_transfers": transfers,
            "hop2_transfers": hop2_transfers,
        }
        n_flagged = sum(1 for s in top if s.flags)
        summary = (
            f"taint {taint_pct:g}% of {_money(inbound)} traced; "
            f"{n_flagged} of {len(top)} top senders flagged"
        )
        if hop2:
            summary += f"; hop 2 on {len({e['via'] for e in hop2})}"
        if failed:
            summary += f"; partial: {len(failed)} of {len(feeds)} feeds failed"
        return CheckOutcome(
            name=NAME, status="ok", latency_ms=int((time.monotonic() - t0) * 1000),
            summary=summary, data=data, raw=raw,
        )

    # ---------- Blockscout ----------

    def _host(self, chain_id: int) -> str | None:
        if self._key:
            return f"{self._base}/{chain_id}"
        return KEYLESS_HOSTS.get(chain_id)

    async def _fetch(self, hop: int, chain_id: int, feed: str, address: str, dl: _Deadline, *, reserve: float) -> _Feed:
        host = self._host(chain_id)
        params = dict(FEED_PARAMS[feed])
        shown = f"{host}{FEED_PATHS[feed].format(address=address)}?{urlencode(params)}" if host else ""
        out = _Feed(hop=hop, chain_id=chain_id, feed=feed, address=address, url=shown)
        if host is None:
            out.error = f"no keyless Blockscout host for chain {chain_id} (set BLOCKSCOUT_API_KEY)"
            return out
        if self._key:
            params["apikey"] = self._key
        url = host + FEED_PATHS[feed].format(address=address)
        for attempt in range(3):  # first try + 2 retries on 429/5xx
            retry_after = None
            async with self._sem:
                remaining = dl.remaining() - reserve
                if remaining < 0.3 or not await self._limiter.acquire(max_wait=remaining - 0.3):
                    out.error = out.error or "time budget exhausted"
                    return out
                limit = max(0.3, min(PER_CALL_TIMEOUT_S, dl.remaining() - reserve))
                try:
                    # httpx timeouts are per phase (connect, read, ...); asyncio.timeout
                    # caps the whole request so the trace budget holds.
                    async with asyncio.timeout(limit):
                        resp = await self._http.get(
                            url, params=params, headers={"Accept": "application/json"}, timeout=limit
                        )
                except (httpx.TimeoutException, TimeoutError):
                    out.error = "timed out"
                    return out
                except httpx.HTTPError as exc:
                    out.error = f"request failed: {type(exc).__name__}"
                    resp = None
            if resp is not None:
                out.status = resp.status_code
                if resp.status_code == 200:
                    try:
                        body = resp.json()
                    except ValueError:
                        body = None
                    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
                        out.error = "non-JSON or unexpected response (bot challenge on a keyless host?)"
                        return out
                    out.items = body["items"][: self.page_size]
                    out.next_page = bool(body.get("next_page_params")) or len(body["items"]) > self.page_size
                    out.error = None
                    return out
                out.error = f"HTTP {resp.status_code}"
                if resp.status_code == 403 and "just a moment" in resp.text.lower():
                    out.error += " (bot challenge on the keyless host; set BLOCKSCOUT_API_KEY)"
                if resp.status_code not in _RETRYABLE:
                    return out
                retry_after = _int(resp.headers.get("retry-after"))
            if attempt == 2:
                break
            backoff = 0.3 * (2**attempt)
            if retry_after is not None and 0 < retry_after <= 2:
                backoff = float(retry_after)
            if dl.remaining() - reserve < backoff + 0.3:
                break
            await asyncio.sleep(backoff)
        return out

    # ---------- normalisation ----------

    def _normalise(self, feeds: list[_Feed], target: str, drops: Counter) -> tuple[list[dict], dict]:
        transfers: list[dict] = []
        senders: dict[tuple[str, int], _Sender] = {}
        target_l = target.lower()
        for f in feeds:
            if f.error:
                continue
            for item in f.items:
                if not isinstance(item, dict):
                    continue
                t = self._normalise_item(f.feed, f.chain_id, item, target_l, drops)
                if t is None:
                    continue
                transfers.append(t)
                key = (t["from"], f.chain_id)
                s = senders.get(key)
                if s is None:
                    labels, match, is_scam = sender_info(item.get("from"))
                    s = senders[key] = _Sender(t["from"], f.chain_id, labels=labels, match=match, is_scam=is_scam)
                s.usd += t["usd"]
                s.tx_count += 1
        return transfers, senders

    def _normalise_item(self, feed: str, chain_id: int, item: dict, target_l: str, drops: Counter) -> dict | None:
        frm = (item.get("from") or {}).get("hash")
        if not isinstance(frm, str) or not is_address(frm):
            drops["no_sender"] += 1
            return None
        if frm.lower() == target_l:
            drops["self"] += 1
            return None
        if feed == "erc20":
            tok = item.get("token") or {}
            if tok.get("reputation") == "scam" or tok.get("is_scam"):
                drops["scam_token"] += 1
                return None
            total = item.get("total") or {}
            value = _int(total.get("value"))
            decimals = _int(total.get("decimals"))
            if decimals is None:
                decimals = _int(tok.get("decimals"))
            if not value or value <= 0:
                drops["zero"] += 1
                return None
            tok_addr = str(tok.get("address_hash") or tok.get("address") or "").lower()
            canon = CANONICAL_TOKENS.get((chain_id, tok_addr))
            symbol = tok.get("symbol") or canon or "?"
            amount = self._amount(value, decimals if decimals is not None else 18)
            if canon is not None and canon in self.stablecoins:
                usd = amount
            elif canon == "WETH":
                usd = amount * self.eth_usd
            else:
                usd = 0.0
                if symbol in self.stablecoins or symbol in ("ETH", "WETH"):
                    drops["lookalike"] += 1
            tx_hash = item.get("transaction_hash")
        else:
            if feed == "native":
                if item.get("status") not in (None, "ok") or item.get("result") not in (None, "success"):
                    drops["failed"] += 1
                    return None
                tx_hash = item.get("hash")
            else:
                if item.get("success") is False or item.get("error"):
                    drops["failed"] += 1
                    return None
                tx_hash = item.get("transaction_hash")
            value = _int(item.get("value"))
            if not value or value <= 0:
                drops["zero"] += 1
                return None
            symbol = "ETH"
            amount = self._amount(value, 18)
            usd = amount * self.eth_usd
        return {
            "from": to_checksum_address(frm),
            "chain_id": chain_id,
            "feed": feed,
            "symbol": symbol,
            "amount": amount,
            "usd": round(usd, 6),
            "tx_hash": tx_hash,
        }

    @staticmethod
    def _amount(value: int, decimals: int) -> float:
        if not 0 <= decimals <= 77:
            return 0.0
        try:
            return float(Decimal(value) / (Decimal(10) ** decimals))
        except (InvalidOperation, OverflowError):
            return 0.0

    @staticmethod
    def _drop_notes(drops: Counter, notes: list[str]) -> None:
        parts = []
        for key, label in (
            ("zero", "zero-value"), ("self", "self-transfers"), ("scam_token", "scam-token"),
            ("failed", "failed"), ("no_sender", "sender-less"),
        ):
            if drops.get(key):
                parts.append(f"{drops[key]} {label}")
        if parts:
            notes.append("Dropped " + ", ".join(parts) + " transfers")
        if drops.get("lookalike"):
            notes.append(
                f"{drops['lookalike']} transfers of tokens using a stablecoin or WETH symbol at a "
                "non-canonical address were valued at $0"
            )

    # ---------- flags ----------

    async def _flag_hop1(self, top: list[_Sender], dl: _Deadline, notes: list[str]) -> None:
        if not top:
            return
        addrs = list(dict.fromkeys(s.address for s in top))
        budget = max(0.2, dl.remaining() - 0.2)
        oracle_task = self._oracle_many(addrs, min(1.9, budget))
        scan_tasks = [self._funder_scan(a, budget) for a in addrs]
        oracle_res, *scans = await asyncio.gather(oracle_task, *scan_tasks)
        scan_by_addr = dict(zip(addrs, scans))

        oracle_missing = 0
        scan_status: Counter = Counter()
        for s in top:
            flags: list[str] = []
            chains = oracle_res.get(s.address) or {}
            if any(v is True for v in chains.values()):
                s.sanctioned = True
                flags.append("sanctioned")
            elif all(v is None for v in chains.values()):
                oracle_missing += 1
            outcome = scan_by_addr.get(s.address)
            if outcome is not None and outcome.status == "ok" and isinstance(outcome.data, dict):
                score = outcome.data.get("toxicScore")
                traits = [t.get("name") for t in outcome.data.get("traits") or [] if isinstance(t, dict)]
                s.intercepta = {"toxicScore": score, "traits": traits}
                flags += [f"intercepta:{t}" for t in traits if t in self.risky_traits]
                if isinstance(score, (int, float)) and score >= self.hold_score:
                    flags.append("intercepta:toxic_score")
            else:
                scan_status[(outcome.status, outcome.error or outcome.summary) if outcome else ("error", "no result")] += 1
            flags += label_flags(s.match, s.is_scam, self.keywords)
            s.flags = list(dict.fromkeys(flags))
        if oracle_missing:
            notes.append(f"Sanctions oracle unavailable for {_n(oracle_missing, 'hop-1 sender')}")
        for (status, detail), n in scan_status.items():
            notes.append(f"Intercepta funder scans {status} for {_n(n, 'sender')}: {detail}")

    async def _oracle_many(self, addresses: list[str], budget_s: float) -> dict:
        if not addresses:
            return {}
        try:
            return await self.oracle.check_many(addresses, budget_s=budget_s)
        except Exception:  # the oracle client should not raise; degrade to "unknown"
            log.exception("oracle check_many failed")
            return {}

    async def _funder_scan(self, address: str, budget: float):
        try:
            return await asyncio.wait_for(self.intercepta.quick_scan_cached(address), timeout=budget)
        except asyncio.TimeoutError:
            return CheckOutcome(name="intercepta.quick_scan", status="error", summary="timed out",
                                error="timed out within the trace budget")
        except Exception as exc:  # never let a funder scan break the trace
            return CheckOutcome(name="intercepta.quick_scan", status="error", summary=str(exc),
                                error=f"{type(exc).__name__}")

    # ---------- hop 2 ----------

    async def _hop2(self, candidates: list[_Sender], target: str, dl: _Deadline, notes: list[str]):
        vias = list(dict.fromkeys(s.address for s in candidates))
        feeds = await asyncio.gather(
            *(self._fetch(2, 1, f, via, dl, reserve=0.5) for via in vias for f in FEEDS)
        )
        entries: list[dict] = []
        transfers: list[dict] = []
        per_via: dict[str, list[_Sender]] = {}
        for via in vias:
            via_feeds = [f for f in feeds if f.address == via]
            for f in via_feeds:
                if f.error:
                    notes.append(f"hop 2 {_short(via)} {FEED_LABELS[f.feed]} not traced: {f.error}")
            drops: Counter = Counter()
            vt, vs = self._normalise(via_feeds, via, drops)
            vs = {k: s for k, s in vs.items() if s.address != target}
            transfers += [{**t, "via": via} for t in vt if t["from"] != target]
            ranked = sorted(
                (s for s in vs.values() if s.usd >= self.min_usd),
                key=lambda s: (-s.usd, -s.tx_count, s.address),
            )
            per_via[via] = ranked[: self.k2]
        all_addrs = list(dict.fromkeys(s.address for group in per_via.values() for s in group))
        oracle_res = await self._oracle_many(all_addrs, max(0.2, min(1.9, dl.remaining() - 0.15)))
        for via, group in per_via.items():
            for s in group:
                flags: list[str] = []
                chains = oracle_res.get(s.address) or {}
                if any(v is True for v in chains.values()):
                    s.sanctioned = True
                    flags.append("sanctioned")
                flags += label_flags(s.match, s.is_scam, self.keywords)
                entries.append({
                    "via": via, "address": s.address, "chain_id": s.chain_id, "usd": round(s.usd, 2),
                    "tx_count": s.tx_count, "labels": s.labels, "flags": list(dict.fromkeys(flags)),
                })
        return entries, transfers, feeds

    # ---------- output ----------

    def _hop1_entry(self, s: _Sender, inbound: float) -> dict:
        return {
            "address": s.address,
            "chain_id": s.chain_id,
            "usd": round(s.usd, 2),
            "share_pct": round(100.0 * s.usd / inbound, 2) if inbound > 0 else 0.0,
            "tx_count": s.tx_count,
            "labels": s.labels,
            "flags": s.flags,
            "sanctioned": s.sanctioned,
            "intercepta": s.intercepta,
        }

    def _paths(self, top: list[_Sender], hop2: list[dict]) -> list[str]:
        paths = []
        for s in top:
            if s.flags:
                paths.append(
                    f"{s.display} → counterparty ({_chain_name(s.chain_id)}, {_money(s.usd)}) "
                    f"[{', '.join(s.flags)}]"
                )
        for e in hop2:
            if not e["flags"]:
                continue
            src = e["labels"][0] if e["labels"] else _short(e["address"])
            for s in top:
                if s.address == e["via"] and not s.flags:
                    paths.append(
                        f"{src} → {s.display} → counterparty ({_chain_name(s.chain_id)}, "
                        f"{_money(s.usd)} x {self.w2:g}) [{', '.join(e['flags'])}]"
                    )
        return paths
