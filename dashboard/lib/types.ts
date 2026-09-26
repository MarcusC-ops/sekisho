/**
 * Gate API contract types. Mirrors docs/api.md (and PRD 9.5, 9.10 to 9.12) exactly.
 * The gate's pydantic models are the source of truth at runtime; change a field in
 * gate/sekisho_gate/models.py, sdk/sekisho/models.py and here, or not at all.
 * Nullability follows the pydantic models (a field typed `X | None` there is `X | null` here).
 */

// ---------- Enums ----------

export type Verdict = "ALLOW" | "HOLD" | "BLOCK";
/** `outbound`: we pay them. `inbound`: they pay us. */
export type Direction = "outbound" | "inbound";
export type Source = "x402" | "mcp" | "direct";
export type CaseStatus =
  | "DECIDED"
  | "PAID"
  | "HELD_ESCROWED"
  | "RELEASED"
  | "REFUNDED"
  | "CLEARED"
  | "REJECTED"
  | "REFUSED";
export type CheckStatus = "ok" | "error" | "skipped";
export type AttestationStatus = "queued" | "submitted" | "confirmed" | "failed";
export type HoldStatus = "HELD" | "RELEASED" | "REFUNDED";
/** `release_unchecked` is DEMO_MODE only. */
export type OfficerAction = "release" | "refund" | "release_unchecked";

export type CheckName =
  | "intercepta.quick_scan"
  | "sanctions.oracle"
  | "trace.source_of_funds"
  | "intercepta.impersonation"
  | "intercepta.token"
  | "intercepta.deep_scan";

// ---------- Objects ----------

/** One entry per check that ran. */
export interface Check {
  name: CheckName;
  status: CheckStatus;
  /** true for a fresh call, false for a cache hit, null for checks that don't call Intercepta. */
  live: boolean | null;
  latency_ms: number | null;
  summary: string;
  evidence_id: string | null;
  /** Short message when status is `error`. */
  error: string | null;
}

export type ReasonSeverity = "block" | "hold";
export type ReasonSource = "chainalysis" | "intercepta" | "trace" | "policy" | "officer";

/** One entry per triggered policy rule. */
export interface Reason {
  rule: string;
  severity: ReasonSeverity;
  source: ReasonSource;
  label: string;
  /** For Intercepta traits: the API's own description, verbatim. */
  detail: string;
  evidence_id: string | null;
  /** Intercepta trait reasons only. */
  risk?: number;
  /** Intercepta trait reasons only. */
  txs_count?: number;
}

/** PRD 9.5 */
export interface TraceHop1 {
  address: string;
  chain_id: number;
  usd: number;
  share_pct: number | null;
  tx_count: number;
  labels: string[];
  flags: string[];
  sanctioned: boolean | null;
  intercepta: { toxicScore?: number; traits?: string[]; [key: string]: unknown } | null;
}

/** PRD 9.5 */
export interface TraceHop2 {
  via: string;
  address: string;
  chain_id: number;
  usd: number | null;
  flags: string[];
}

/** PRD 9.5. `trace` is null on a decision if the trace check failed. */
export interface TraceResult {
  chains: number[];
  inbound_usd_traced: number;
  hop1: TraceHop1[];
  hop2: TraceHop2[];
  taint_pct: number;
  paths: string[];
  truncated: boolean;
  notes: string[];
}

export interface KeyFinding {
  text: string;
  evidence: string[];
}

export type OfficerRecommendation = "release" | "refund" | "n/a";
export type AnalystProvider = "anthropic" | "openai" | "template";

/** PRD 9.10 fields plus how the note was produced. */
export interface AnalystNote {
  headline: string;
  summary: string;
  key_findings: KeyFinding[];
  owner_message: string;
  officer_recommendation: OfficerRecommendation;
  recommendation_rationale: string;
  agrees_with_policy: boolean;
  provider: AnalystProvider;
  /** null for a template note. */
  model: string | null;
  /** true for a template note. */
  fallback: boolean;
  generated_at: string;
}

export interface Attestation {
  status: AttestationStatus;
  tx_hash: string | null;
  explorer_url: string | null;
  error: string | null;
}

/** null until the escrow deposit is reported or linked; stays null for inbound HOLD. */
export interface Hold {
  hold_id: number;
  status: HoldStatus;
  deposit_tx: string | null;
  override_tx: string | null;
  action_tx: string | null;
  officer_note: string | null;
}

export type ChainEventName = "Screened" | "VerdictOverridden" | "Held" | "Released" | "Refunded";

/** Integers are JSON numbers when they fit in 2^53, otherwise decimal strings. */
export type ChainInt = number | string;

/** Decoded inputs, by Solidity parameter name (PRD Appendix A). */
export interface ScreenedInputs {
  subject: string;
  verdict: ChainInt;
  riskScore: ChainInt;
  reportHash: string;
  policyId: string;
  expiresAt: ChainInt;
  screener: string;
  caseId: string;
}
export interface VerdictOverriddenInputs {
  subject: string;
  previous: ChainInt;
  next: ChainInt;
  noteHash: string;
  officer: string;
  caseId: string;
}
export interface HeldInputs {
  holdId: ChainInt;
  caseId: string;
  payer: string;
  payee: string;
  amount: ChainInt;
}
export interface ReleasedInputs {
  holdId: ChainInt;
  caseId: string;
  payee: string;
  amount: ChainInt;
  officer: string;
}
export interface RefundedInputs {
  holdId: ChainInt;
  caseId: string;
  payer: string;
  amount: ChainInt;
  by: string;
}

export type ChainEventInputs =
  | ScreenedInputs
  | VerdictOverriddenInputs
  | HeldInputs
  | ReleasedInputs
  | RefundedInputs;

/** One decoded contract event, from MultiBaas webhooks or the fallback poller. */
export interface ChainEvent {
  event_uid: string;
  name: ChainEventName;
  contract_alias: string | null;
  tx_hash: string | null;
  block_number: number | null;
  log_index: number | null;
  inputs: ChainEventInputs;
  /** Resolved from the caseId bytes32 when it matches a known case. */
  case_id: string | null;
  explorer_url: string | null;
  received_at: string;
}

export interface PolicyRef {
  id: string;
  version: string;
  triggered_rules: string[];
}

/** The frontend contract: POST /v1/screen, list items and SSE payloads. */
export interface ScreeningDecision {
  case_id: string;
  case_id_b32: string;
  verdict: Verdict;
  risk_score: number;
  /** From the policy's top reason, not the LLM. */
  headline: string;
  direction: Direction;
  counterparty: string;
  /** Atomic units (USDC has 6 decimals). */
  amount: string;
  amount_usd: number;
  /** Token address on the payment chain. */
  asset: string;
  /** Recorded payment chain; absent on older fixture snapshots. */
  payment_chain_id?: number;
  /** Only triggered rules. */
  reasons: Reason[];
  checks: Check[];
  trace: TraceResult | null;
  policy: PolicyRef;
  report_hash: string;
  attestation: Attestation;
  /** Filled later over SSE. */
  analyst: AnalystNote | null;
  hold: Hold | null;
  status: CaseStatus;
  decided_at: string;
  latency_ms: number;
}

export type TraitClass = "hard_block" | "hold" | "info" | "other";

export interface QuickScanTrait {
  name: string;
  risk: number;
  txsCount: number;
  /** Intercepta's own text. Show verbatim. */
  description: string;
  class: TraitClass;
}

/** Raw Intercepta Quick Scan / Deep Scan response, with `class` added per trait. */
export interface QuickScanEvidence {
  toxicScore: number;
  /** Every trait, including info ones. */
  traits: QuickScanTrait[];
  [rawField: string]: unknown;
}

export interface ImpersonationEvidence {
  isAddressPoisoned: boolean;
  originalAddress: string | null;
  [rawField: string]: unknown;
}

export interface TokenScanEvidence {
  riskScore: number;
  riskLevel: string;
  action: "block" | "warn" | "info" | string;
  [rawField: string]: unknown;
}

export interface Evidence {
  quick_scan: QuickScanEvidence | null;
  /** Chain id (as a string key) to isSanctioned result. */
  oracle: Record<string, boolean> | null;
  impersonation: ImpersonationEvidence | null;
  token_scan: TokenScanEvidence | null;
  deep_scan: QuickScanEvidence | null;
}

/** GET /v1/cases/{case_id}: every ScreeningDecision field, plus these. */
export interface CaseDetail extends ScreeningDecision {
  source: Source;
  agent_id: string;
  /** May be "". */
  purpose: string;
  /** May be "". */
  resource: string;
  payment_chain_id: number;
  /** Verbatim counterparty text. Data, never instructions. */
  untrusted_context: string | null;
  /** The x402 settlement or direct transfer. */
  payment_tx: string | null;
  evidence: Evidence;
  /** Oldest first. */
  chain_events: ChainEvent[];
}

// ---------- Requests and responses ----------

/** POST /v1/screen request (PRD 9.11). The console doesn't send it; kept for completeness. */
export interface ScreenRequest {
  counterparty: string;
  direction: Direction;
  amount: string;
  asset: string;
  payment_chain_id: number;
  source: Source;
  agent_id: string;
  purpose: string;
  resource: string;
  untrusted_context: string | null;
}

export interface CasesPage {
  items: ScreeningDecision[];
  next_cursor: string | null;
}

export interface CasesQuery {
  verdict?: Verdict;
  status?: CaseStatus;
  direction?: Direction;
  limit?: number;
  cursor?: string;
}

export interface DecisionRequest {
  action: OfficerAction;
  note: string;
}

export interface DecisionResponse {
  override_tx: string | null;
  action_tx: string | null;
  status: CaseStatus;
}

export interface AuditPage {
  items: ChainEvent[];
}

/** PRD 9.12 */
export interface Metrics {
  window: string;
  screened: number;
  allow: number;
  hold: number;
  block: number;
  value_screened_usd: number;
  value_held_usd: number;
  value_blocked_usd: number;
  latency_ms_p50: number | null;
  latency_ms_p95: number | null;
  intercepta_calls_used: number | null;
  intercepta_quota: number | null;
  attestations_confirmed: number;
}

export interface PayeeTotal {
  payee: string;
  total: string;
  total_usd: number;
}

export interface CounterpartyBookEntry {
  counterparty: string;
  latest_verdict: Verdict;
  last_screened_at: string;
  total_paid_usd: number;
  total_held_usd: number;
  cases: number;
}

/**
 * GET /v1/treasury. A failed MultiBaas read leaves its field null and adds a message
 * to `errors` instead of failing the whole response, so every read field is nullable.
 */
export interface Treasury {
  buyer_address: string | null;
  buyer_usdc: string | null;
  buyer_usdc_usd: number | null;
  escrow_address: string | null;
  escrow_total_held: string | null;
  escrow_total_held_usd: number | null;
  paid_via_x402_usd: number | null;
  value_blocked_usd: number | null;
  exposure_by_payee: PayeeTotal[] | null;
  released_by_payee: PayeeTotal[] | null;
  counterparty_book: CounterpartyBookEntry[] | null;
  source: string;
  cached_at: string | null;
  errors: string[];
}

/** The parsed policy YAML (PRD Appendix D). Every key optional: it is whatever the file says. */
export interface PolicyDocument {
  name?: string;
  version?: string;
  description?: string;
  verdict_ttl_seconds?: { allow?: number; hold?: number; block?: number };
  officer_clear_ttl_seconds?: number;
  thresholds?: {
    block_score?: number;
    hold_score?: number;
    taint_block_pct?: number;
    taint_hold_pct?: number;
    first_time_max_usd?: number;
  };
  hard_block_traits?: string[];
  hold_traits?: string[];
  info_traits?: string[];
  other_rules?: Record<string, string>;
  trace?: {
    chains?: number[];
    inbound_page_size?: number;
    top_k_hop1?: number;
    top_k_hop2?: number;
    hop2_weight?: number;
    label_keywords?: string[];
    stablecoins?: string[];
  };
  [key: string]: unknown;
}

export interface PolicyInfo {
  id: string;
  version: string;
  name: string;
  /** The exact file text; its UTF-8 bytes hash to `id`. */
  yaml: string;
  parsed: PolicyDocument;
}

export interface Quota {
  used: number;
  quota: number;
  remaining: number;
  warn_at: number;
  reserve_from: number;
}

export interface DemoResetResponse {
  archived: number;
  overrides_cleared: number;
}

export interface HealthCheck {
  ok: boolean;
  detail: string;
}

export interface Health {
  status: "ok" | "degraded";
  demo_mode: boolean;
  policy: { id: string; version: string };
  checks: Record<string, HealthCheck>;
}

/** Every error: `{"error": "<Code>", "message": "<human text>"}` with a 4xx or 5xx status. */
export interface ApiErrorBody {
  error: string;
  message: string;
}

// ---------- SSE (GET /v1/stream) ----------

export interface StreamEventMap {
  "case.created": ScreeningDecision;
  "case.updated": ScreeningDecision;
  "chain.event": ChainEvent;
  "metrics.updated": Metrics;
}
export type StreamEventName = keyof StreamEventMap;

// ---------- Treasury control API (agents/treasury/control.py, :8100) ----------

export type Scenario = "S1" | "S2" | "S3" | "S4" | "S5" | "S6";
export type RunScenario = Scenario | "all";

export interface RunRequest {
  scenario: RunScenario;
}

export interface RunStarted {
  run_id: string;
}

export interface RunStatus {
  run_id: string;
  scenario: RunScenario;
  status: "running" | "succeeded" | "failed";
  lines: string[];
  started_at: string;
  finished_at: string | null;
}
