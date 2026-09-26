"""Pydantic schemas for the gate API: the runtime source of truth for docs/api.md.

The SDK (sdk/sekisho/models.py) and the console (dashboard/lib/types.ts) mirror these.
Change a field in all three, or not at all.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from eth_utils import is_address, is_checksum_address, to_checksum_address
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
)

# ---------- enums ----------

Verdict = Literal["ALLOW", "HOLD", "BLOCK"]
Direction = Literal["outbound", "inbound"]
Source = Literal["x402", "mcp", "direct"]
CaseStatus = Literal[
    "DECIDED", "PAID", "HELD_ESCROWED", "RELEASED", "REFUNDED", "CLEARED", "REJECTED", "REFUSED"
]
CheckStatus = Literal["ok", "error", "skipped"]
AttestationStatus = Literal["queued", "submitted", "confirmed", "failed"]
HoldStatus = Literal["HELD", "RELEASED", "REFUNDED"]
OfficerAction = Literal["release", "refund", "release_unchecked"]
Severity = Literal["block", "hold"]
ReasonSource = Literal["chainalysis", "intercepta", "trace", "policy", "officer"]
Recommendation = Literal["release", "refund", "n/a"]
Provider = Literal["anthropic", "openai", "template"]
TraitClass = Literal["hard_block", "hold", "info", "other"]
ChainEventName = Literal["Screened", "VerdictOverridden", "Held", "Released", "Refunded"]

VERDICT_CODE = {"ALLOW": 1, "HOLD": 2, "BLOCK": 3}  # ComplianceRegistry.Verdict
VERDICT_BY_CODE = {v: k for k, v in VERDICT_CODE.items()}

# ---------- field types ----------

_HEX32 = re.compile(r"^0x[0-9a-fA-F]{64}$")
_DIGITS = re.compile(r"^[0-9]{1,78}$")


def _checksum(value: Any) -> str:
    if not isinstance(value, str) or not is_address(value) or not value.startswith("0x"):
        raise ValueError("not a valid EVM address (expect 0x + 40 hex characters)")
    body = value[2:]
    # EIP-55: all-lowercase or all-uppercase carry no checksum; mixed case must be a
    # valid checksum (eth_utils 6 is_address no longer checks it, so check here).
    if body != body.lower() and body != body.upper() and not is_checksum_address(value):
        raise ValueError("invalid EIP-55 checksum (mixed-case address with a wrong checksum)")
    return to_checksum_address(value)


def _hex32(value: Any) -> str:
    if not isinstance(value, str) or not _HEX32.match(value):
        raise ValueError("expect 0x + 64 hex characters")
    return value.lower()


def _atomic_amount(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("amount must be an atomic-unit string")
    if isinstance(value, int) and value >= 0:
        value = str(value)
    if not isinstance(value, str) or not _DIGITS.match(value):
        raise ValueError('amount must be a non-negative integer string in atomic units, e.g. "50000"')
    return str(int(value))  # strip leading zeros


Address = Annotated[str, AfterValidator(_checksum)]
Hex32 = Annotated[str, AfterValidator(_hex32)]
AtomicAmount = Annotated[str, BeforeValidator(_atomic_amount)]


# ---------- requests ----------


class ScreenRequest(BaseModel):
    """POST /v1/screen (PRD 9.11)."""

    counterparty: Address
    direction: Direction
    amount: AtomicAmount
    asset: Address
    payment_chain_id: int = Field(default=84532, ge=1)
    source: Source = "direct"
    agent_id: str = Field(default="", max_length=200)
    purpose: str = Field(default="", max_length=2000)
    resource: str = Field(default="", max_length=2000)
    untrusted_context: str | None = Field(default=None, max_length=65536)


class PaymentReport(BaseModel):
    tx_hash: Hex32
    network: str = Field(default="eip155:84532", max_length=64)


class HoldReport(BaseModel):
    hold_id: int = Field(ge=1)
    deposit_tx: Hex32


class DecisionRequest(BaseModel):
    action: OfficerAction
    note: str = Field(default="", max_length=4000)


# ---------- decision parts ----------


class Check(BaseModel):
    name: str
    status: CheckStatus
    live: bool | None = None
    latency_ms: int | None = None
    summary: str = ""
    evidence_id: str | None = None
    error: str | None = None


class Reason(BaseModel):
    rule: str
    severity: Severity
    source: ReasonSource
    label: str
    detail: str
    evidence_id: str | None = None
    risk: int | None = None  # Intercepta trait reasons only
    txs_count: int | None = None  # Intercepta trait reasons only

    @model_serializer(mode="wrap")
    def _omit_trait_fields(self, handler):
        data = handler(self)
        for key in ("risk", "txs_count"):
            if data.get(key) is None:
                data.pop(key, None)
        return data


class TraceHop1(BaseModel):
    model_config = ConfigDict(extra="allow")
    address: str
    chain_id: int
    usd: float = 0.0
    share_pct: float | None = None
    tx_count: int = 0
    labels: list[str] = []
    flags: list[str] = []
    sanctioned: bool | None = None
    intercepta: dict[str, Any] | None = None


class TraceHop2(BaseModel):
    model_config = ConfigDict(extra="allow")
    via: str
    address: str
    chain_id: int
    usd: float | None = None
    flags: list[str] = []


class TraceResult(BaseModel):
    """PRD 9.5. The gate passes the tracer's dict through; this model documents it."""

    model_config = ConfigDict(extra="allow")
    chains: list[int] = []
    inbound_usd_traced: float = 0.0
    hop1: list[TraceHop1] = []
    hop2: list[TraceHop2] = []
    taint_pct: float = 0.0
    paths: list[str] = []
    truncated: bool = False
    notes: list[str] = []


class KeyFinding(BaseModel):
    text: str
    evidence: list[str] = []


class AnalystOutput(BaseModel):
    """What the LLM must return (PRD 9.10 / Appendix E.1)."""

    headline: str
    summary: str
    key_findings: list[KeyFinding] = []
    owner_message: str
    officer_recommendation: Recommendation
    recommendation_rationale: str
    agrees_with_policy: bool

    @field_validator("key_findings", mode="before")
    @classmethod
    def _at_most_five(cls, value: Any) -> Any:
        return value[:5] if isinstance(value, list) else value


class AnalystNote(AnalystOutput):
    provider: Provider
    model: str | None = None
    fallback: bool = False
    generated_at: str


class Attestation(BaseModel):
    status: AttestationStatus
    tx_hash: str | None = None
    explorer_url: str | None = None
    error: str | None = None


class Hold(BaseModel):
    hold_id: int
    status: HoldStatus
    deposit_tx: str | None = None
    override_tx: str | None = None
    action_tx: str | None = None
    officer_note: str | None = None


class PolicyRef(BaseModel):
    id: str
    version: str
    triggered_rules: list[str]


class ChainEvent(BaseModel):
    event_uid: str
    name: str
    contract_alias: str | None = None
    tx_hash: str | None = None
    block_number: int | None = None
    log_index: int | None = None
    inputs: dict[str, Any] = {}
    case_id: str | None = None
    explorer_url: str | None = None
    received_at: str


class ScreeningDecision(BaseModel):
    """The frontend contract: POST /v1/screen, lists and SSE."""

    case_id: str
    case_id_b32: str
    verdict: Verdict
    risk_score: int = Field(ge=0, le=100)
    headline: str
    direction: Direction
    counterparty: str
    amount: str
    amount_usd: float
    asset: str
    payment_chain_id: int = Field(default=0, ge=0)
    reasons: list[Reason]
    checks: list[Check]
    trace: dict[str, Any] | None = None  # TraceResult (PRD 9.5), or null if the trace failed
    policy: PolicyRef
    report_hash: str
    attestation: Attestation
    analyst: AnalystNote | None = None
    hold: Hold | None = None
    status: CaseStatus
    decided_at: str
    latency_ms: int


class Evidence(BaseModel):
    quick_scan: dict[str, Any] | None = None
    oracle: dict[str, Any] | None = None
    impersonation: dict[str, Any] | None = None
    token_scan: dict[str, Any] | None = None
    deep_scan: dict[str, Any] | None = None


class CaseDetail(ScreeningDecision):
    source: str
    agent_id: str
    purpose: str
    resource: str
    payment_chain_id: int
    untrusted_context: str | None = None
    payment_tx: str | None = None
    evidence: Evidence
    chain_events: list[ChainEvent] = []


# ---------- responses ----------


class CaseList(BaseModel):
    items: list[ScreeningDecision]
    next_cursor: str | None = None


class PaymentAck(BaseModel):
    case_id: str
    status: CaseStatus


class HoldAck(BaseModel):
    case_id: str
    status: CaseStatus


class DecisionResult(BaseModel):
    override_tx: str | None = None
    action_tx: str | None = None
    status: CaseStatus


class Metrics(BaseModel):
    window: str = "since_reset"
    screened: int
    allow: int
    hold: int
    block: int
    value_screened_usd: float
    value_held_usd: float
    value_blocked_usd: float
    latency_ms_p50: int | None = None
    latency_ms_p95: int | None = None
    intercepta_calls_used: int | None = None
    intercepta_quota: int | None = None
    attestations_confirmed: int


class AuditList(BaseModel):
    items: list[ChainEvent]


class PayeeTotal(BaseModel):
    payee: str
    total: str
    total_usd: float


class CounterpartyBookEntry(BaseModel):
    counterparty: str
    latest_verdict: Verdict
    last_screened_at: str
    total_paid_usd: float
    total_held_usd: float
    cases: int


class Treasury(BaseModel):
    buyer_address: str | None = None
    buyer_usdc: str | None = None
    buyer_usdc_usd: float | None = None
    escrow_address: str | None = None
    escrow_total_held: str | None = None
    escrow_total_held_usd: float | None = None
    paid_via_x402_usd: float | None = None
    value_blocked_usd: float | None = None
    exposure_by_payee: list[PayeeTotal] | None = None
    released_by_payee: list[PayeeTotal] | None = None
    counterparty_book: list[CounterpartyBookEntry] | None = None
    source: str = "multibaas"
    cached_at: str | None = None
    errors: list[str] = []


class PolicyInfo(BaseModel):
    id: str
    version: str
    name: str
    yaml: str
    parsed: dict[str, Any]


class Quota(BaseModel):
    used: int
    quota: int
    remaining: int
    warn_at: int
    reserve_from: int


class DemoResetResult(BaseModel):
    archived: int
    overrides_cleared: int


class HealthCheck(BaseModel):
    ok: bool
    detail: str


class HealthPolicy(BaseModel):
    id: str
    version: str


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    demo_mode: bool
    policy: HealthPolicy
    checks: dict[str, HealthCheck]


class ErrorBody(BaseModel):
    error: str
    message: str
