"""Candidate scan (PRD 7.3, P0): pick the demo counterparties from live screening data.

    make scan                                   built-in list + the treasury wallet
    .venv/bin/python scripts/scan_candidates.py candidates.txt 0xabc… [--max-calls 20]

For each candidate, in-process with the gate's own clients and policy engine (no case, no
attestation, no transaction): a live Intercepta Quick Scan, the Chainalysis sanctions
oracle and a hop-1 source-of-funds trace, then the policy's predicted verdict. Prints
`address, toxicScore, traits, oracle, taint_pct, predicted verdict`, suggests addresses
for VENDOR_CLEAN_PAYTO (S1) and VENDOR_MIXER_PAYTO (S2), and writes scan_results.json
(gitignored). The treasury wallet is scanned as a payer (inbound) and must come out
ALLOW, or the vendors would refuse S1's payment.

Quota (PRD 11.4, 20 calls budgeted): direct scans run first, one live call each; the
tracer's funder scans use cached results where they exist and stop at --max-calls (the
tracer then flags funders with the oracle and Blockscout labels only). Impersonation and
token scans are not run; the gate runs them on real payments.

A candidate file has one address per line, optionally followed by a label; # comments.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eth_account import Account  # noqa: E402
from eth_utils import is_address, to_checksum_address  # noqa: E402

from sekisho_gate.checks import ORACLE, QUICK_SCAN, TRACE  # noqa: E402
from sekisho_gate.screening.types import CheckOutcome  # noqa: E402

RESULTS = ROOT / "scan_results.json"
PRICE_USD = 0.05  # vendor price: first_time_large (> $25) never applies
DEFAULT_MAX_CALLS = 20
BUILTIN = [  # PRD 7.3
    ("0x098B716B8Aaf21512996dC57EB0615e2383E2f96", "sanctioned: Ronin Bridge exploiter (S3, S4)"),
    ("0xa0e1c89Ef1a489c9C7dE96311eD5Ce5D32c20E4B", "sanctioned backup / S5 rogue payer"),
]
S2_TRAITS = ("mixer_transfers", "sanction_address_communication", "non_kyc_transfers")


# ---------- candidates ----------


def read_candidates(args: list[str]) -> list[tuple[str, str]]:
    """Addresses from positional args: an address, or a file of `address [label]` lines."""
    out: list[tuple[str, str]] = []
    for arg in args:
        if is_address(arg):
            out.append((to_checksum_address(arg), "command line"))
            continue
        path = Path(arg)
        if not path.is_file():
            raise SystemExit(f"{arg}: not an address and not a file")
        for n, line in enumerate(path.read_text().splitlines(), 1):
            text = line.split("#", 1)[0].strip().replace(",", " ")
            if not text:
                continue
            address, _, label = text.partition(" ")
            if not is_address(address):
                raise SystemExit(f"{arg}:{n}: {address!r} is not an address")
            out.append((to_checksum_address(address), label.strip() or path.name))
    return out


def default_candidates(settings: Any) -> list[tuple[str, str]]:
    out = list(BUILTIN)
    for attr, label in (("vendor_clean_payto", "current VENDOR_CLEAN_PAYTO (S1)"),
                        ("vendor_mixer_payto", "current VENDOR_MIXER_PAYTO (S2)")):
        value = getattr(settings, attr)
        if value and is_address(value):
            out.append((to_checksum_address(value), label))
    return out


def dedupe(candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: dict[str, tuple[str, str]] = {}
    for address, label in candidates:
        seen.setdefault(address.lower(), (address, label))
    return list(seen.values())


# ---------- the quota-capped Intercepta wrapper ----------


class Budget:
    """Wraps the gate's InterceptaClient. Counts HTTP calls through the gate's own quota
    counter (shared SQLite), and once `max_calls` is reached answers funder scans that
    would need a network call with `skipped`."""

    def __init__(self, client: Any, max_calls: int):
        from sekisho_gate.screening.cache import QUOTA_KEY

        self.client, self.max_calls, self._key = client, max_calls, QUOTA_KEY
        self.start = client.cache.value(QUOTA_KEY)

    @property
    def used(self) -> int:
        return self.client.cache.value(self._key) - self.start

    @property
    def exhausted(self) -> bool:
        return self.used >= self.max_calls

    async def quick_scan(self, address: str, *, live: bool = True) -> CheckOutcome:
        return await self.client.quick_scan(address, live=live)

    async def quick_scan_cached(self, address: str) -> CheckOutcome:
        if self.client.cache.get("quick_scan", address.lower()) is None and self.exhausted:
            return CheckOutcome(name=QUICK_SCAN, status="skipped", summary="skipped: --max-calls reached")
        return await self.client.quick_scan_cached(address)  # counts itself before any await


# ---------- scan ----------


def summarise(address: str, label: str, direction: str, outcomes: dict[str, CheckOutcome],
              policy: Any) -> dict[str, Any]:
    qs, oracle, trace = outcomes.get(QUICK_SCAN), outcomes.get(ORACLE), outcomes.get(TRACE)
    decision = policy.evaluate(outcomes, amount_usd=PRICE_USD, direction=direction)
    qs_data = qs.data if qs is not None and qs.status == "ok" and isinstance(qs.data, dict) else {}
    tr = trace.data if trace is not None and trace.status == "ok" and isinstance(trace.data, dict) else None
    return {
        "address": address,
        "label": label,
        "direction": direction,
        "quick_scan": None if qs is None else {
            "status": qs.status, "live": qs.live, "latency_ms": qs.latency_ms, "error": qs.error,
            "toxicScore": qs_data.get("toxicScore"),
            "traits": policy.classified_traits(qs_data.get("traits")),  # descriptions verbatim
        },
        "oracle": None if oracle is None else {"status": oracle.status, "result": oracle.data, "error": oracle.error},
        "trace": None if trace is None else {
            "status": trace.status, "error": trace.error, "latency_ms": trace.latency_ms,
            "taint_pct": tr.get("taint_pct") if tr else None,
            "inbound_usd_traced": tr.get("inbound_usd_traced") if tr else None,
            "hop1": [{k: h.get(k) for k in ("address", "chain_id", "usd", "share_pct", "labels", "flags")}
                     for h in (tr.get("hop1") or [])] if tr else [],
            "paths": tr.get("paths") if tr else [],
            "notes": tr.get("notes") if tr else [],
        },
        "predicted": {"verdict": decision.verdict, "risk_score": decision.risk_score,
                      "headline": decision.headline, "triggered_rules": decision.triggered_rules},
    }


def suggest_roles(rows: list[dict[str, Any]], buyer: str | None) -> dict[str, list[str]]:
    """PRD 7.3: S1 must be ALLOW; S2 needs a HOLD-level trait and nothing that turns it
    into a BLOCK (no hard-block trait, toxicScore < 80, oracle false, taint < 50%)."""
    s1, s2, s3 = [], [], []
    for r in rows:
        if buyer and r["address"].lower() == buyer.lower():
            continue
        p, qs, oracle = r["predicted"], r["quick_scan"] or {}, (r["oracle"] or {}).get("result") or {}
        traits = {t["name"]: t["class"] for t in qs.get("traits") or []}
        if p["verdict"] == "ALLOW":
            s1.append(r["address"])
        if (p["verdict"] == "HOLD" and any(t in traits for t in S2_TRAITS)
                and "hard_block" not in traits.values() and (qs.get("toxicScore") or 0) < 80
                and not any(v is True for v in oracle.values())
                and ((r["trace"] or {}).get("taint_pct") or 0) < 50):
            s2.append(r["address"])
        if p["verdict"] == "BLOCK" and any(v is True for v in oracle.values()):
            s3.append(r["address"])
    return {"VENDOR_CLEAN_PAYTO (S1, ALLOW)": s1, "VENDOR_MIXER_PAYTO (S2, HOLD) + 2 backups": s2,
            "VENDOR_SANCTIONED_PAYTO (S3/S4, BLOCK)": s3}


def row_line(r: dict[str, Any]) -> str:
    qs = r["quick_scan"] or {}
    if qs.get("status") == "ok":
        score = str(qs.get("toxicScore"))
        traits = ", ".join(t["name"] for t in qs.get("traits") or []) or "-"
    else:
        score, traits = qs.get("status") or "-", qs.get("error") or ""
    oracle = (r["oracle"] or {}).get("result") or {}
    oracle_text = " ".join(f"{'ETH' if k == '1' else 'BASE'}={str(v).lower()}" for k, v in oracle.items()) or "error"
    taint = (r["trace"] or {}).get("taint_pct")
    taint_text = f"{taint:.1f}%" if isinstance(taint, (int, float)) else (r["trace"] or {}).get("status", "-")
    p = r["predicted"]
    rules = ", ".join(p["triggered_rules"]) or "no rule"
    return (f"{r['address']}  toxicScore {score:<4} oracle {oracle_text:<21} taint {taint_text:<6} "
            f"→ {p['verdict']:<5} ({rules})\n    {r['label']}{' · as payer (inbound)' if r['direction'] == 'inbound' else ''}"
            f" · traits: {traits}")


async def scan(candidates: list[tuple[str, str]], buyer: str | None, settings: Any, max_calls: int,
               emit: Any = print) -> dict[str, Any]:
    from sekisho_gate.policy.engine import Policy
    from sekisho_gate.screening.intercepta import InterceptaClient
    from sekisho_gate.screening.sanctions import SanctionsOracle
    from sekisho_gate.screening.tracer import Tracer

    hop1 = settings.model_copy(update={"trace_enable_hop2": False})  # PRD 7.3: hop 1 only
    policy = Policy(settings.policy_path)
    intercepta = InterceptaClient(hop1)
    budget = Budget(intercepta, max_calls)
    oracle = SanctionsOracle(hop1)
    tracer = Tracer(hop1, oracle, budget, policy.parsed)
    targets = [(a, label, "outbound") for a, label in candidates]
    if buyer:
        targets.append((buyer, "treasury agent wallet (vendors screen it as the payer)", "inbound"))
    try:
        # Direct scans first, so the funder scans can't starve them of quota.
        quick: dict[str, CheckOutcome] = {}
        for address, _, _ in targets:
            if budget.exhausted:
                quick[address] = CheckOutcome(name=QUICK_SCAN, status="skipped", summary="--max-calls reached",
                                              error="not scanned: --max-calls reached")
                continue
            quick[address] = await budget.quick_scan(address, live=True)
        rows = []
        for address, label, direction in targets:
            emit(f"… {address}: oracle and hop-1 trace")
            oracle_outcome, trace_outcome = await asyncio.gather(oracle.check(address), tracer.trace(address))
            outcomes = {QUICK_SCAN: quick[address], ORACLE: oracle_outcome, TRACE: trace_outcome}
            rows.append(summarise(address, label, direction, outcomes, policy))
    finally:
        for client in (tracer, oracle, intercepta):
            await client.aclose()
    return {
        "scanned_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "policy": policy.ref(),
        "hop2": False,
        "amount_usd": PRICE_USD,
        "intercepta_calls_used": budget.used,
        "max_calls": max_calls,
        "quota": intercepta.quota_status(),
        "buyer": buyer,
        "results": rows,
        "suggestions": suggest_roles(rows, buyer),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Screen candidate counterparties (PRD 7.3)")
    parser.add_argument("candidates", nargs="*", help="addresses or files (default: the built-in list)")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS,
                        help=f"Intercepta HTTP calls this run may spend (default {DEFAULT_MAX_CALLS})")
    parser.add_argument("--no-buyer", action="store_true", help="skip the treasury wallet")
    args = parser.parse_args(argv)

    from sekisho_gate.config import get_settings

    settings = get_settings()
    if not settings.intercepta_api_key.get_secret_value().strip():
        print("INTERCEPTA_API_KEY is not set in .env: the scan needs live Intercepta data.", file=sys.stderr)
        return 2
    candidates = dedupe(read_candidates(args.candidates) if args.candidates else default_candidates(settings))
    buyer = None
    if not args.no_buyer:
        key = settings.buyer_agent_pk.get_secret_value()
        buyer = Account.from_key(key).address if key else None
        if buyer is None:
            print("! BUYER_AGENT_PK is not set: the treasury wallet is not scanned (run make wallets)")
    candidates = [c for c in candidates if not buyer or c[0].lower() != buyer.lower()]
    print(f"Scanning {len(candidates)} candidates{' + the treasury wallet' if buyer else ''} "
          f"(max {args.max_calls} Intercepta calls, hop-1 trace, policy {settings.policy_path.name})")

    report = asyncio.run(scan(candidates, buyer, settings, args.max_calls))
    print()
    for row in report["results"]:
        print(row_line(row))
    print()
    for role, addresses in report["suggestions"].items():
        print(f"{role}: {', '.join(addresses) if addresses else 'none found'}")
    warn = 0
    if buyer:
        mine = next(r for r in report["results"] if r["address"] == buyer)
        if mine["predicted"]["verdict"] != "ALLOW":
            warn = 1
            print(f"\n! WARNING: the treasury wallet {buyer} comes out {mine['predicted']['verdict']}: vendors "
                  "would refuse its payments in S1. Generate a fresh BUYER_AGENT_PK.")
    RESULTS.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    q = report["quota"]
    print(f"\nIntercepta calls used by this scan: {report['intercepta_calls_used']} "
          f"(quota {q['used']}/{q['quota']}, {q['remaining']} left) · wrote {RESULTS.relative_to(ROOT)}")
    return warn


if __name__ == "__main__":
    sys.exit(main())
