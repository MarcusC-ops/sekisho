"""Pydantic mirror of the gate's ScreeningDecision (docs/api.md, PRD 9.11).

Standalone on purpose, so the SDK installs without the gate. `extra="allow"` everywhere:
a field the gate adds later passes through instead of breaking older SDKs. `verdict` is
strict, so an unknown verdict fails validation and the client reports the gate as
unavailable (fail closed) instead of guessing. Times stay as the ISO 8601 strings the
gate sent.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["ALLOW", "HOLD", "BLOCK"]
Direction = Literal["outbound", "inbound"]
Source = Literal["x402", "mcp", "direct"]

# Kept as plain strings so a new gate value doesn't break old SDKs. Values per docs/api.md:
# CaseStatus: DECIDED PAID HELD_ESCROWED RELEASED REFUNDED CLEARED REJECTED REFUSED
# CheckStatus: ok error skipped. AttestationStatus: queued submitted confirmed failed.
# HoldStatus: HELD RELEASED REFUNDED.


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


class Check(_Model):
    """One check that ran, e.g. `intercepta.quick_scan` (live, latency)."""

    name: str
    status: str
    live: bool | None = None
    latency_ms: int | None = None
    summary: str = ""
    evidence_id: str | None = None
    error: str | None = None


class Reason(_Model):
    """One triggered policy rule. `risk` and `txs_count` only appear on Intercepta traits."""

    rule: str
    severity: str
    source: str
    label: str
    detail: str = ""
    evidence_id: str | None = None
    risk: int | None = None
    txs_count: int | None = None


class KeyFinding(_Model):
    text: str
    evidence: list[str] = Field(default_factory=list)


class AnalystNote(_Model):
    """Advisory only: the AI explains, the policy decides."""

    headline: str = ""
    summary: str = ""
    key_findings: list[KeyFinding] = Field(default_factory=list)
    owner_message: str = ""
    officer_recommendation: str = "n/a"
    recommendation_rationale: str = ""
    agrees_with_policy: bool | None = None
    provider: str = "template"
    model: str | None = None
    fallback: bool = False
    generated_at: str | None = None


class Attestation(_Model):
    status: str = "queued"
    tx_hash: str | None = None
    explorer_url: str | None = None
    error: str | None = None


class Hold(_Model):
    hold_id: int
    status: str
    deposit_tx: str | None = None
    override_tx: str | None = None
    action_tx: str | None = None
    officer_note: str | None = None


class PolicyRef(_Model):
    id: str
    version: str
    triggered_rules: list[str] = Field(default_factory=list)


class Decision(_Model):
    """ScreeningDecision: what `POST /v1/screen` returns (also used in lists and SSE)."""

    case_id: str
    case_id_b32: str
    verdict: Verdict
    risk_score: int
    headline: str
    direction: Direction
    counterparty: str
    amount: str
    amount_usd: float
    asset: str
    # Zero marks an older gate response without chain binding; payer hooks refuse it.
    payment_chain_id: int = Field(default=0, ge=0)
    reasons: list[Reason] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    trace: dict[str, Any] | None = None
    policy: PolicyRef
    report_hash: str
    attestation: Attestation = Field(default_factory=Attestation)
    analyst: AnalystNote | None = None
    hold: Hold | None = None
    status: str
    decided_at: str
    latency_ms: int

    @property
    def allowed(self) -> bool:
        return self.verdict == "ALLOW"

    def check(self, name: str) -> Check | None:
        """The named check (e.g. `intercepta.quick_scan`), or None if it didn't run."""
        return next((c for c in self.checks if c.name == name), None)
