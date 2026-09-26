"""Deterministic policy engine (PRD 9.6, Appendix D).

The same evidence always gives the same verdict. The policy file is hashed byte for
byte into `policy_id`; it is never reformatted or re-serialised here.

Evaluation (PRD 9.6 table): every triggered rule is collected for the reasons list and
the strongest outcome wins (BLOCK > HOLD > ALLOW). Rule 0 (officer override): a BLOCK
override is BLOCK; an ALLOW override skips rules 3 to 6 and 8 to 12, while rules 1, 2
and 7 always apply (sanctions and fail-closed are never overridden). `info_traits`
never change the verdict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml
from eth_utils import keccak

from ..checks import (
    CHAIN_NAMES,
    EVIDENCE_IDS,
    IMPERSONATION,
    ORACLE,
    QUICK_SCAN,
    TOKEN,
    TRACE,
)
from ..screening.types import CheckOutcome
from ..util import iso as _iso

SEVERITY_RANK = {"block": 2, "hold": 1}
VERDICT_FOR_SEVERITY = {"block": "BLOCK", "hold": "HOLD"}

# Policy-derived headlines (never the LLM, never a paraphrase of Intercepta text).
_TRAIT_HEADLINES = {
    "sanction_address": "Counterparty is on a sanctions list",
    "known_scammer": "Counterparty is a known scammer",
    "initiator_scam_transactions": "Counterparty initiated scam transactions",
    "blacklist": "Counterparty is blacklisted",
    "sanction_address_communication": "Counterparty has dealt with sanctioned addresses",
    "mixer_transfers": "Counterparty has mixer exposure",
    "non_kyc_transfers": "Counterparty has non-KYC exchange exposure",
    "fake_phishing_contract_communication": "Counterparty has interacted with phishing contracts",
    "rug_pull": "Counterparty is linked to a rug pull",
    "rug_pull_trader": "Counterparty traded a rug-pull token",
    "suspicious_deployer": "Counterparty is a suspicious contract deployer",
    "suspicious_dex_pair_deployer": "Counterparty is a suspicious DEX pair deployer",
    "attack_money_target": "Counterparty is linked to attack funds",
}
_RULE_HEADLINES = {
    "officer_override": "Counterparty blocked by a compliance officer",
    "sanctions_oracle": "Counterparty is on a sanctions list",
    "address_poisoned": "Counterparty address imitates another address (address poisoning)",
    "token_block": "Payment token is flagged as high risk",
    "toxic_score_block": "Counterparty risk score is above the block threshold",
    "taint_block": "Most traced funds come from flagged sources",
    "toxic_score_hold": "Counterparty risk score needs review",
    "taint_hold": "Part of the traced funds come from flagged sources",
    "token_warn": "Payment token has risk warnings",
    "first_time_large": "First payment to a new counterparty is above the limit",
}
HEADLINE_ALLOW = "No policy rule triggered"
HEADLINE_ALLOW_OVERRIDE = "Cleared by a compliance officer"


@dataclass(frozen=True)
class Override:
    """An active officer override for a counterparty (store: officer_overrides)."""

    verdict: str  # "ALLOW" or "BLOCK"
    expires_at: int  # unix seconds
    case_id: str | None = None
    tx_hash: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "expires_at": self.expires_at,
            "case_id": self.case_id,
            "tx_hash": self.tx_hash,
        }


@dataclass
class PolicyDecision:
    verdict: str
    risk_score: int
    reasons: list[dict[str, Any]]
    triggered_rules: list[str]
    headline: str
    override: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _int_or_none(value: Any) -> int | None:
    f = _num(value)
    return None if f is None else int(round(f))


def _fmt_num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _ok_data(outcome: CheckOutcome | None) -> dict[str, Any] | None:
    if outcome is None or outcome.status != "ok" or not isinstance(outcome.data, dict):
        return None
    return outcome.data


def quick_scan_data(outcome: CheckOutcome | None) -> dict[str, Any] | None:
    """The Quick Scan data if the check succeeded AND has the documented shape
    (`toxicScore` a number, `traits` a list), else None. Anything unexpected counts as
    a failed scan, so rule 7 fails closed."""
    data = _ok_data(outcome)
    if data is None or _num(data.get("toxicScore")) is None or not isinstance(data.get("traits"), list):
        return None
    return data


class Policy:
    """Loads policy.yaml, exposes its id and parameters, and evaluates evidence."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.raw_bytes: bytes = self.path.read_bytes()
        self.id: str = "0x" + keccak(self.raw_bytes).hex()
        self.yaml_text: str = self.raw_bytes.decode("utf-8")
        self.parsed: dict[str, Any] = yaml.safe_load(self.raw_bytes)
        p = self.parsed
        self.name: str = str(p["name"])
        self.version: str = str(p["version"])
        t = p["thresholds"]
        self.block_score = float(t["block_score"])
        self.hold_score = float(t["hold_score"])
        self.taint_block_pct = float(t["taint_block_pct"])
        self.taint_hold_pct = float(t["taint_hold_pct"])
        self.first_time_max_usd = float(t["first_time_max_usd"])
        self.hard_block_traits: list[str] = list(p.get("hard_block_traits") or [])
        self.hold_traits: list[str] = list(p.get("hold_traits") or [])
        self.info_traits: list[str] = list(p.get("info_traits") or [])
        ttl = p["verdict_ttl_seconds"]
        self.verdict_ttl = {"ALLOW": int(ttl["allow"]), "HOLD": int(ttl["hold"]), "BLOCK": int(ttl["block"])}
        self.officer_clear_ttl_seconds = int(p["officer_clear_ttl_seconds"])

    # ---------- helpers ----------

    def ttl_for(self, verdict: str) -> int:
        return self.verdict_ttl[verdict]

    def classify_trait(self, name: str) -> str:
        if name in self.hard_block_traits:
            return "hard_block"
        if name in self.hold_traits:
            return "hold"
        if name in self.info_traits:
            return "info"
        return "other"

    def classified_traits(self, traits: Any) -> list[dict[str, Any]]:
        """Every trait (info ones included) with its policy class, for the evidence view."""
        out = []
        for t in traits or []:
            if isinstance(t, dict):
                out.append({**t, "class": self.classify_trait(str(t.get("name", "")))})
        return out

    def ref(self) -> dict[str, str]:
        return {"id": self.id, "version": self.version, "name": self.name}

    # ---------- evaluation ----------

    def evaluate(
        self,
        checks: Mapping[str, CheckOutcome | None],
        *,
        amount_usd: float,
        direction: str = "outbound",
        override: Override | None = None,
        has_prior_allow: bool = False,
    ) -> PolicyDecision:
        qs = checks.get(QUICK_SCAN)
        qs_data = quick_scan_data(qs)  # None unless ok AND well-formed (fail closed)
        toxic = _num(qs_data.get("toxicScore")) if qs_data is not None else None
        traits = [t for t in qs_data["traits"] if isinstance(t, dict)] if qs_data is not None else []

        oracle = checks.get(ORACLE)
        oracle_data = oracle.data if oracle is not None and isinstance(oracle.data, dict) else {}
        trace_data = _ok_data(checks.get(TRACE))
        taint = _num(trace_data.get("taint_pct")) if trace_data else None
        imp_data = _ok_data(checks.get(IMPERSONATION))
        tok_data = _ok_data(checks.get(TOKEN))

        allow_override = override is not None and override.verdict == "ALLOW"
        block_override = override is not None and override.verdict == "BLOCK"

        reasons: list[dict[str, Any]] = []
        triggered: list[str] = []
        floors: list[int] = []

        def hit(
            rule: str,
            severity: str,
            source: str,
            label: str,
            detail: str,
            evidence_id: str | None,
            floor: int | None = None,
            risk: Any = None,
            txs_count: Any = None,
        ) -> None:
            if rule in triggered:
                return
            triggered.append(rule)
            if floor is not None:
                floors.append(floor)
            reason: dict[str, Any] = {
                "rule": rule,
                "severity": severity,
                "source": source,
                "label": label,
                "detail": detail,
                "evidence_id": evidence_id,
            }
            if source == "intercepta" and rule.startswith(("hard_block_trait:", "hold_trait:")):
                reason["risk"] = _int_or_none(risk)
                reason["txs_count"] = _int_or_none(txs_count)
            reasons.append(reason)

        # Rule 0: officer override.
        if override is not None:
            if block_override:
                hit(
                    "officer_override",
                    "block",
                    "officer",
                    "Blocked by a compliance officer",
                    f"Officer override BLOCK active until {_iso(override.expires_at)}"
                    + (f" (case {override.case_id})" if override.case_id else ""),
                    None,
                )
            else:
                triggered.append("officer_override")  # ALLOW: no block/hold reason

        # Rule 1: sanctions oracle (always applies).
        sanctioned = [cid for cid, v in oracle_data.items() if v is True]
        if sanctioned:
            names = " and ".join(CHAIN_NAMES.get(str(c), f"chain {c}") for c in sorted(sanctioned, key=str))
            hit(
                "sanctions_oracle",
                "block",
                "chainalysis",
                "Sanctioned address (onchain oracle)",
                f"isSanctioned = true on {names}",
                EVIDENCE_IDS[ORACLE],
                floor=100,
            )

        # Rule 2: hard-block traits (always apply).
        for t in traits:
            name = str(t.get("name", ""))
            if name in self.hard_block_traits:
                hit(
                    f"hard_block_trait:{name}",
                    "block",
                    "intercepta",
                    name,
                    _verbatim(t.get("description")),
                    EVIDENCE_IDS[QUICK_SCAN],
                    floor=95,
                    risk=t.get("risk"),
                    txs_count=t.get("txsCount"),
                )

        if not allow_override:
            # Rule 3: address poisoning.
            if imp_data and imp_data.get("isAddressPoisoned") is True:
                original = imp_data.get("originalAddress")
                hit(
                    "address_poisoned",
                    "block",
                    "intercepta",
                    "Address poisoning lookalike",
                    "isAddressPoisoned = true"
                    + (f"; imitates {original}" if original else ""),
                    EVIDENCE_IDS[IMPERSONATION],
                    floor=90,
                )
            # Rule 4: token scan action block.
            if tok_data and str(tok_data.get("action", "")).lower() == "block":
                hit(
                    "token_block",
                    "block",
                    "intercepta",
                    "Payment token flagged: block",
                    _token_detail(tok_data),
                    EVIDENCE_IDS[TOKEN],
                    floor=90,
                )
            # Rule 5: toxic score at or above the block threshold.
            if toxic is not None and toxic >= self.block_score:
                hit(
                    "toxic_score_block",
                    "block",
                    "intercepta",
                    "Intercepta toxicScore at or above the block threshold",
                    f"toxicScore {_fmt_num(toxic)} ≥ {_fmt_num(self.block_score)}",
                    EVIDENCE_IDS[QUICK_SCAN],
                )
            # Rule 6: taint at or above the block threshold.
            if taint is not None and taint >= self.taint_block_pct:
                hit(
                    "taint_block",
                    "block",
                    "trace",
                    "Source of funds: high taint",
                    _taint_detail(taint, self.taint_block_pct, trace_data),
                    EVIDENCE_IDS[TRACE],
                )

        # Rule 7: fail closed when the Quick Scan failed (always applies).
        if qs_data is None:
            hit(
                "screening_error",
                "hold",
                "policy",
                "Screening unavailable (fail closed)",
                _screening_error_detail(qs),
                EVIDENCE_IDS[QUICK_SCAN],
                floor=50,
            )

        if not allow_override:
            # Rule 8: hold traits.
            for t in traits:
                name = str(t.get("name", ""))
                if name in self.hold_traits:
                    hit(
                        f"hold_trait:{name}",
                        "hold",
                        "intercepta",
                        name,
                        _verbatim(t.get("description")),
                        EVIDENCE_IDS[QUICK_SCAN],
                        floor=50,
                        risk=t.get("risk"),
                        txs_count=t.get("txsCount"),
                    )
            # Rule 9: toxic score at or above the hold threshold.
            if toxic is not None and toxic >= self.hold_score:
                hit(
                    "toxic_score_hold",
                    "hold",
                    "intercepta",
                    "Intercepta toxicScore at or above the hold threshold",
                    f"toxicScore {_fmt_num(toxic)} ≥ {_fmt_num(self.hold_score)}",
                    EVIDENCE_IDS[QUICK_SCAN],
                )
            # Rule 10: taint at or above the hold threshold.
            if taint is not None and taint >= self.taint_hold_pct:
                hit(
                    "taint_hold",
                    "hold",
                    "trace",
                    "Source of funds: taint",
                    _taint_detail(taint, self.taint_hold_pct, trace_data),
                    EVIDENCE_IDS[TRACE],
                    floor=45,
                )
            # Rule 11: token scan action warn.
            if tok_data and str(tok_data.get("action", "")).lower() == "warn":
                hit(
                    "token_warn",
                    "hold",
                    "intercepta",
                    "Payment token flagged: warn",
                    _token_detail(tok_data),
                    EVIDENCE_IDS[TOKEN],
                    floor=40,
                )
            # Rule 12: first payment to a new counterparty above the limit.
            if not has_prior_allow and amount_usd > self.first_time_max_usd:
                hit(
                    "first_time_large",
                    "hold",
                    "policy",
                    "First-time counterparty above the limit",
                    f"No prior ALLOW or PAID case for this counterparty; amount "
                    f"{amount_usd:,.2f} USD > {_fmt_num(self.first_time_max_usd)} USD",
                    None,
                    floor=40,
                )

        # Rule 13: default.
        if reasons:
            top = max(reasons, key=lambda r: SEVERITY_RANK[r["severity"]])  # first of the strongest
            verdict = VERDICT_FOR_SEVERITY[top["severity"]]
            headline = self._headline(top, direction)
        elif allow_override:
            verdict, headline = "ALLOW", HEADLINE_ALLOW_OVERRIDE
        else:
            verdict, headline = "ALLOW", HEADLINE_ALLOW
            triggered.append("default")

        # risk_score = min(100, max(toxicScore, max trait risk of hard-block and hold
        # traits, round(taint_pct), all triggered floors))
        trait_risks = [
            _num(t.get("risk")) or 0.0
            for t in traits
            if str(t.get("name", "")) in self.hard_block_traits + self.hold_traits
        ]
        parts = [toxic or 0.0, max(trait_risks, default=0.0), float(round(taint or 0.0)), *map(float, floors)]
        risk_score = int(round(min(100.0, max(0.0, *parts))))

        return PolicyDecision(
            verdict=verdict,
            risk_score=risk_score,
            reasons=reasons,
            triggered_rules=triggered,
            headline=headline,
            override=override.as_dict() if override else None,
        )

    def _headline(self, reason: dict[str, Any], direction: str) -> str:
        rule = reason["rule"]
        if rule == "screening_error":
            return (
                "Screening unavailable, payment held"
                if direction == "outbound"
                else "Screening unavailable, payer held for review"
            )
        if rule.startswith(("hard_block_trait:", "hold_trait:")):
            name = rule.split(":", 1)[1]
            if name in _TRAIT_HEADLINES:
                return _TRAIT_HEADLINES[name]
            level = "hard-block" if rule.startswith("hard_block") else "hold-level"
            return f"Counterparty has a {level} risk trait ({name})"
        return _RULE_HEADLINES.get(rule, "Policy rule triggered")


def _verbatim(description: Any) -> str:
    """Intercepta's own description text, unchanged (AGENTS.md rule 8)."""
    return description if isinstance(description, str) else ("" if description is None else str(description))


def _token_detail(tok: dict[str, Any]) -> str:
    bits = [f"action = {tok.get('action')}"]
    for key in ("riskLevel", "riskScore", "trust"):
        if tok.get(key) is not None:
            bits.append(f"{key} = {tok.get(key)}")
    codes = [d.get("code") for d in tok.get("detectors") or [] if isinstance(d, dict) and d.get("code")]
    if codes:
        bits.append("detectors: " + ", ".join(str(c) for c in codes))
    return "; ".join(bits)


def _taint_detail(taint: float, threshold: float, trace: dict[str, Any] | None) -> str:
    text = f"taint {taint:.1f}% of traced inbound value from flagged sources (threshold {_fmt_num(threshold)}%)"
    paths = (trace or {}).get("paths") or []
    if paths:
        text += "; " + "; ".join(str(p) for p in paths[:3])
    return text


def _screening_error_detail(qs: CheckOutcome | None) -> str:
    tail = "Policy fails closed: never ALLOW on missing data."
    if qs is None:
        return f"Intercepta Quick Scan did not run. {tail}"
    if qs.status == "ok":
        return f"Intercepta Quick Scan returned no usable data. {tail}"
    what = qs.error or qs.summary or qs.status
    return f"Intercepta Quick Scan {qs.status}: {what}. {tail}"
