/**
 * An in-browser stand-in for the gate and the treasury control API, built from
 * dashboard/fixtures. FOR CONSOLE DEVELOPMENT ONLY: it is loaded (dynamically) only when
 * NEXT_PUBLIC_USE_FIXTURES=true, and the console then shows a "FIXTURE DATA" banner.
 *
 * It answers the same paths as the real APIs (docs/api.md), simulates the SSE stream by
 * periodically "creating" cases from scenario templates, and simulates officer decisions
 * (override tx, then release/refund tx) and demo-bar runs.
 */
import { keccak256, stringToBytes } from "viem";
import auditJson from "@/fixtures/audit.json";
import casesJson from "@/fixtures/cases.json";
import healthJson from "@/fixtures/health.json";
import policyJson from "@/fixtures/policy.json";
import reportsJson from "@/fixtures/reports.json";
import scenariosJson from "@/fixtures/scenarios.json";
import { canonical } from "@/lib/canonical.mjs";
import { EXPLORER_URL } from "@/lib/config";
import { GateError } from "@/lib/errors";
import { shortAddress } from "@/lib/format";
import type {
  CaseDetail,
  CasesPage,
  ChainEvent,
  CounterpartyBookEntry,
  DecisionRequest,
  DecisionResponse,
  Health,
  Metrics,
  PayeeTotal,
  PolicyInfo,
  Quota,
  RunRequest,
  RunScenario,
  RunStarted,
  RunStatus,
  Scenario,
  ScreeningDecision,
  StreamEventMap,
  StreamEventName,
  Treasury,
  Verdict,
} from "@/lib/types";
import type { BodyKind, Method, Target } from "@/lib/api";

// ---------------------------------------------------------------- setup

const AUTO_SPAWN_EVERY_MS = 20_000;
const AUTO_SPAWN_LIMIT = 40;
const AUTO_ROTATION: Scenario[] = ["S1", "S3", "S2", "S4", "S5", "S6"];
const VERDICT_CODE: Record<Verdict, number> = { ALLOW: 1, HOLD: 2, BLOCK: 3 };
const TTL: Record<Verdict, number> = { ALLOW: 86400, HOLD: 86400, BLOCK: 31536000 };

const ADDRESSES = scenariosJson.addresses as { buyer: string; officer: string; screener: string; escrow: string };
const TEMPLATE_IDS = scenariosJson.templates as unknown as Record<Scenario, string[]>;
const TEMPLATES = new Map((casesJson as unknown as CaseDetail[]).map((c) => [c.case_id, c]));

const VENDORS: Record<string, { id: string; name: string }> = {
  "4021": { id: "vendor-clean", name: "Kabuto Market Data" },
  "4022": { id: "vendor-mixer", name: "Nightowl Analytics" },
  "4023": { id: "vendor-sanctioned", name: "Ronin Signals" },
  "4024": { id: "vendor-injection", name: "Oracle Feeds Pro" },
};

interface State {
  cases: CaseDetail[]; // newest first, not archived
  archived: CaseDetail[];
  reports: Record<string, string>;
  audit: ChainEvent[]; // newest first
  interceptaUsed: number;
  nextHoldId: number;
  blockCursor: number;
  runs: Map<string, RunStatus>;
  activeRun: string | null;
  autoSpawned: number;
}

let state: State | null = null;

const isoOf = (ms: number) => new Date(Math.floor(ms / 1000) * 1000).toISOString().replace(".000Z", "Z");
const isoNow = () => isoOf(Date.now());
const shiftIso = (iso: string | null, offset: number) => (iso ? isoOf(Date.parse(iso) + offset) : iso);
const clone = <T>(value: T): T => structuredClone(value);
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const later = (ms: number, fn: () => void) => void setTimeout(fn, ms);

function randomHex(bytes: number): string {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return `0x${Array.from(buf, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}

const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
function newCaseId(ms: number): string {
  let t = ms;
  let time = "";
  for (let i = 0; i < 10; i += 1) {
    time = CROCKFORD[t % 32] + time;
    t = Math.floor(t / 32);
  }
  const rand = new Uint8Array(16);
  crypto.getRandomValues(rand);
  return `cs_${time}${Array.from(rand, (b) => CROCKFORD[b % 32]).join("")}`;
}

/** Fixtures are dated on demo day; rebase them so the newest case is about 90 s old. */
function getState(): State {
  if (state) return state;
  const cases = clone(casesJson as unknown as CaseDetail[]);
  const audit = clone(auditJson as unknown as ChainEvent[]);
  const newest = Math.max(...cases.map((c) => Date.parse(c.decided_at)));
  const offset = Date.now() - 90_000 - newest;
  const shiftEvent = (e: ChainEvent) => {
    e.received_at = shiftIso(e.received_at, offset) as string;
    if (e.name === "Screened" && "expiresAt" in e.inputs) {
      e.inputs.expiresAt = Number(e.inputs.expiresAt) + Math.round(offset / 1000);
    }
  };
  for (const c of cases) {
    c.decided_at = shiftIso(c.decided_at, offset) as string;
    if (c.analyst) c.analyst.generated_at = shiftIso(c.analyst.generated_at, offset) as string;
    c.chain_events.forEach(shiftEvent);
  }
  audit.forEach(shiftEvent);
  state = {
    cases,
    archived: [],
    reports: { ...(reportsJson as Record<string, string>) },
    audit,
    interceptaUsed: 212,
    nextHoldId: Math.max(0, ...cases.map((c) => c.hold?.hold_id ?? 0)) + 1,
    blockCursor: Math.max(...audit.map((e) => e.block_number ?? 0)),
    runs: new Map(),
    activeRun: null,
    autoSpawned: 0,
  };
  return state;
}

// ---------------------------------------------------------------- stream

type Listener = <K extends StreamEventName>(event: K, data: StreamEventMap[K]) => void;
const listeners = new Set<Listener>();
let autoTimer: ReturnType<typeof setInterval> | null = null;

function emit<K extends StreamEventName>(event: K, data: StreamEventMap[K]) {
  for (const listener of listeners) listener(event, clone(data));
}

/** Subscribe to the simulated SSE stream. Starts the periodic case simulation. */
export function subscribeFixtureStream(listener: Listener): () => void {
  listeners.add(listener);
  if (!autoTimer) {
    autoTimer = setInterval(() => {
      const s = getState();
      if (s.activeRun || s.autoSpawned >= AUTO_SPAWN_LIMIT) return;
      const scenario = AUTO_ROTATION[s.autoSpawned % AUTO_ROTATION.length];
      s.autoSpawned += 1;
      TEMPLATE_IDS[scenario].forEach((id, i) => later(i * 2000, () => spawnFromTemplate(id)));
    }, AUTO_SPAWN_EVERY_MS);
  }
  return () => {
    listeners.delete(listener);
    if (!listeners.size && autoTimer) {
      clearInterval(autoTimer);
      autoTimer = null;
    }
  };
}

// ---------------------------------------------------------------- derived views

const DECISION_KEYS = [
  "case_id",
  "case_id_b32",
  "verdict",
  "risk_score",
  "headline",
  "direction",
  "counterparty",
  "amount",
  "amount_usd",
  "asset",
  "reasons",
  "checks",
  "trace",
  "policy",
  "report_hash",
  "attestation",
  "analyst",
  "hold",
  "status",
  "decided_at",
  "latency_ms",
] as const satisfies readonly (keyof ScreeningDecision)[];

function toDecision(c: CaseDetail): ScreeningDecision {
  const out: Partial<Record<keyof ScreeningDecision, unknown>> = {};
  for (const key of DECISION_KEYS) out[key] = c[key];
  return clone(out) as ScreeningDecision;
}

function findCase(caseId: string): CaseDetail {
  const s = getState();
  const found = s.cases.find((c) => c.case_id === caseId) ?? s.archived.find((c) => c.case_id === caseId);
  if (!found) throw new GateError(404, "not_found", `No case ${caseId}.`);
  return found;
}

function percentile(values: number[], p: number): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length))];
}

const round2 = (n: number) => Math.round(n * 100) / 100;
const sumUsd = (list: CaseDetail[]) => round2(list.reduce((s, c) => s + c.amount_usd, 0));

function metrics(): Metrics {
  const { cases, interceptaUsed } = getState();
  return {
    window: "since_reset",
    screened: cases.length,
    allow: cases.filter((c) => c.verdict === "ALLOW").length,
    hold: cases.filter((c) => c.verdict === "HOLD").length,
    block: cases.filter((c) => c.verdict === "BLOCK").length,
    value_screened_usd: sumUsd(cases),
    value_held_usd: sumUsd(cases.filter((c) => c.verdict === "HOLD")),
    value_blocked_usd: sumUsd(cases.filter((c) => c.verdict === "BLOCK")),
    latency_ms_p50: percentile(cases.map((c) => c.latency_ms), 50),
    latency_ms_p95: percentile(cases.map((c) => c.latency_ms), 95),
    intercepta_calls_used: interceptaUsed,
    intercepta_quota: 1000,
    attestations_confirmed: cases.filter((c) => c.attestation.status === "confirmed").length,
  };
}

function listCases(params: URLSearchParams): CasesPage {
  const verdict = params.get("verdict");
  const status = params.get("status");
  const direction = params.get("direction");
  const limit = Math.min(100, Math.max(1, Number(params.get("limit") ?? 50) || 50));
  const offset = Number((params.get("cursor") ?? "o:0").slice(2)) || 0;
  const matching = getState().cases.filter(
    (c) => (!verdict || c.verdict === verdict) && (!status || c.status === status) && (!direction || c.direction === direction),
  );
  const page = matching.slice(offset, offset + limit);
  return {
    items: page.map(toDecision),
    next_cursor: offset + limit < matching.length ? `o:${offset + limit}` : null,
  };
}

function auditList(params: URLSearchParams) {
  const caseId = params.get("case_id");
  const limit = Math.max(1, Number(params.get("limit") ?? 100) || 100);
  const items = getState().audit.filter((e) => !caseId || e.case_id === caseId).slice(0, limit);
  return { items: clone(items) };
}

function byPayee(list: CaseDetail[]): PayeeTotal[] {
  const totals = new Map<string, number>();
  for (const c of list) totals.set(c.counterparty, (totals.get(c.counterparty) ?? 0) + Number(c.amount));
  return [...totals.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([payee, total]) => ({ payee, total: String(total), total_usd: total / 1e6 }));
}

/** Onchain-derived values use every case: a demo reset archives cases but never touches the chain. */
function treasury(): Treasury {
  const s = getState();
  const all = [...s.cases, ...s.archived];
  const holds = all.filter((c) => c.hold);
  const inEscrow = holds.filter((c) => c.hold?.status === "HELD");
  const paid = all.filter((c) => c.status === "PAID" && c.direction === "outbound");
  const spent = [...paid, ...holds.filter((c) => c.hold?.status !== "REFUNDED")].reduce((n, c) => n + Number(c.amount), 0);
  const buyer = 5_000_000 - spent;

  const book = new Map<string, CounterpartyBookEntry>();
  for (const c of [...s.cases].reverse()) {
    const entry = book.get(c.counterparty) ?? {
      counterparty: c.counterparty,
      latest_verdict: c.verdict,
      last_screened_at: c.decided_at,
      total_paid_usd: 0,
      total_held_usd: 0,
      cases: 0,
    };
    entry.latest_verdict = c.verdict;
    entry.last_screened_at = c.decided_at;
    entry.cases += 1;
    if (c.status === "PAID" || c.status === "RELEASED") entry.total_paid_usd = round2(entry.total_paid_usd + c.amount_usd);
    if (c.status === "HELD_ESCROWED") entry.total_held_usd = round2(entry.total_held_usd + c.amount_usd);
    book.set(c.counterparty, entry);
  }

  const result: Treasury = {
    buyer_address: ADDRESSES.buyer,
    buyer_usdc: String(buyer),
    buyer_usdc_usd: buyer / 1e6,
    escrow_address: ADDRESSES.escrow,
    escrow_total_held: String(inEscrow.reduce((n, c) => n + Number(c.amount), 0)),
    escrow_total_held_usd: sumUsd(inEscrow),
    paid_via_x402_usd: sumUsd(paid.filter((c) => c.source === "x402")),
    value_blocked_usd: sumUsd(all.filter((c) => c.verdict === "BLOCK")),
    exposure_by_payee: byPayee(holds),
    released_by_payee: byPayee(holds.filter((c) => c.hold?.status === "RELEASED")),
    counterparty_book: [...book.values()].sort((a, b) => Date.parse(b.last_screened_at) - Date.parse(a.last_screened_at)),
    source: "multibaas",
    cached_at: isoNow(),
    errors: [],
  };
  // Visit /treasury?fixture=degraded to see how failed MultiBaas reads render.
  if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("fixture") === "degraded") {
    result.buyer_usdc = null;
    result.buyer_usdc_usd = null;
    result.released_by_payee = null;
    result.errors = [
      "usdc.balanceOf(buyer) failed: MultiBaas returned 502 Bad Gateway",
      "Event Query released_by_payee failed: timed out after 10 s",
    ];
  }
  return result;
}

function quota(): Quota {
  const used = getState().interceptaUsed;
  return { used, quota: 1000, remaining: 1000 - used, warn_at: 800, reserve_from: 950 };
}

function health(): Health {
  const h = clone(healthJson) as Health;
  h.checks.intercepta = { ok: true, detail: `key valid, ${getState().interceptaUsed}/1000 used` };
  return h;
}

// ---------------------------------------------------------------- simulated cases

function nextBlock(): number {
  const s = getState();
  s.blockCursor += 1 + Math.floor(Math.random() * 3);
  return s.blockCursor;
}

function chainEvent(name: ChainEvent["name"], alias: string, txHash: string, logIndex: number, inputs: ChainEvent["inputs"], caseId: string): ChainEvent {
  return {
    event_uid: `${txHash}:${logIndex}`,
    name,
    contract_alias: alias,
    tx_hash: txHash,
    block_number: nextBlock(),
    log_index: logIndex,
    inputs,
    case_id: caseId,
    explorer_url: `${EXPLORER_URL}/tx/${txHash}`,
    received_at: isoNow(),
  };
}

function recordEvent(c: CaseDetail, event: ChainEvent) {
  c.chain_events.push(event);
  getState().audit.unshift(event);
  emit("chain.event", event);
}

function publish(c: CaseDetail, kind: "case.created" | "case.updated" = "case.updated") {
  emit(kind, toDecision(c));
}

/** Clone a template case as a brand-new decision, with a fresh report and hash. */
function spawnFromTemplate(templateId: string): CaseDetail {
  const s = getState();
  const tpl = TEMPLATES.get(templateId);
  if (!tpl) throw new Error(`Unknown fixture template ${templateId}`);
  const now = Date.now();
  const caseId = newCaseId(now);
  const caseB32 = keccak256(stringToBytes(caseId));

  const report = JSON.parse(s.reports[tpl.report_hash]) as Record<string, unknown>;
  report.case_id = caseId;
  report.case_id_b32 = caseB32;
  report.decided_at = isoOf(now);
  report.received_at = isoOf(now - tpl.latency_ms);
  const reportText = canonical(report);
  const reportHash = keccak256(stringToBytes(reportText));
  s.reports[reportHash] = reportText;

  const c: CaseDetail = {
    ...clone(tpl),
    case_id: caseId,
    case_id_b32: caseB32,
    report_hash: reportHash,
    decided_at: isoOf(now),
    attestation: { status: "queued", tx_hash: null, explorer_url: null, error: null },
    analyst: null,
    hold: null,
    status: tpl.verdict === "BLOCK" ? "REFUSED" : "DECIDED",
    payment_tx: null,
    chain_events: [],
    // The post-HOLD Deep Scan arrives later; start without it.
    checks: clone(tpl.checks.filter((k) => k.name !== "intercepta.deep_scan")),
    evidence: { ...clone(tpl.evidence), deep_scan: null },
  };
  s.cases.unshift(c);
  s.interceptaUsed += c.checks.filter((k) => k.live === true).length;
  publish(c, "case.created");
  emit("metrics.updated", metrics());

  later(1200, () => {
    if (tpl.analyst) c.analyst = { ...clone(tpl.analyst), generated_at: isoNow() };
    publish(c);
  });
  later(1900, () => {
    const txHash = randomHex(32);
    c.attestation = { status: "submitted", tx_hash: txHash, explorer_url: `${EXPLORER_URL}/tx/${txHash}`, error: null };
    publish(c);
  });
  later(3300, () => {
    const txHash = c.attestation.tx_hash ?? randomHex(32);
    c.attestation = { ...c.attestation, status: "confirmed" };
    recordEvent(
      c,
      chainEvent("Screened", "compliance_registry", txHash, 0, {
        subject: c.counterparty,
        verdict: VERDICT_CODE[c.verdict],
        riskScore: c.risk_score,
        reportHash: c.report_hash,
        policyId: c.policy.id,
        expiresAt: Math.floor(Date.now() / 1000) + TTL[c.verdict],
        screener: ADDRESSES.screener,
        caseId: c.case_id_b32,
      }, c.case_id),
    );
    publish(c);
    emit("metrics.updated", metrics());
  });
  if (c.verdict === "ALLOW" && c.direction === "outbound") {
    later(2600, () => {
      c.status = "PAID";
      c.payment_tx = randomHex(32);
      publish(c);
    });
  }
  if (c.verdict === "HOLD" && c.direction === "outbound") {
    later(2900, () => {
      const holdId = s.nextHoldId;
      s.nextHoldId += 1;
      const depositTx = randomHex(32);
      c.hold = { hold_id: holdId, status: "HELD", deposit_tx: depositTx, override_tx: null, action_tx: null, officer_note: null };
      c.status = "HELD_ESCROWED";
      recordEvent(
        c,
        chainEvent("Held", "compliance_escrow", depositTx, 2, {
          holdId,
          caseId: c.case_id_b32,
          payer: ADDRESSES.buyer,
          payee: c.counterparty,
          amount: Number(c.amount),
        }, c.case_id),
      );
      publish(c);
    });
    const deep = tpl.checks.find((k) => k.name === "intercepta.deep_scan");
    if (deep) {
      later(4600, () => {
        c.checks = [...c.checks, clone(deep)];
        c.evidence = { ...c.evidence, deep_scan: clone(tpl.evidence.deep_scan) };
        s.interceptaUsed += 1;
        publish(c);
      });
    }
  }
  return c;
}

// ---------------------------------------------------------------- officer decisions

async function decide(caseId: string, body: DecisionRequest): Promise<DecisionResponse> {
  const c = findCase(caseId);
  const inbound = c.direction === "inbound";
  const decidable = c.verdict === "HOLD" && (inbound ? c.status === "DECIDED" : c.status === "HELD_ESCROWED");
  if (!decidable) {
    throw new GateError(409, "invalid_state", `Case ${caseId} is ${c.status}. Only HOLD cases in escrow (outbound) or awaiting review (inbound) can be decided.`);
  }
  const holdId = c.hold?.hold_id;
  if (body.action === "release_unchecked") {
    await sleep(900);
    if (inbound || holdId === undefined) {
      throw new GateError(409, "invalid_state", "Release without clearance needs an escrow hold (an outbound HOLD).");
    }
    throw new GateError(409, "NotCleared", `release(${holdId}) reverted: NotCleared (0x92a032ca). The payee has no current ALLOW in the ComplianceRegistry.`);
  }

  const release = body.action === "release";
  await sleep(1400);
  const overrideTx = randomHex(32);
  recordEvent(
    c,
    chainEvent("VerdictOverridden", "compliance_registry", overrideTx, 0, {
      subject: c.counterparty,
      previous: 2,
      next: release ? 1 : 3,
      noteHash: keccak256(stringToBytes(body.note)),
      officer: ADDRESSES.officer,
      caseId: c.case_id_b32,
    }, c.case_id),
  );
  if (inbound || !c.hold) {
    c.status = release ? "CLEARED" : "REJECTED";
    publish(c);
    emit("metrics.updated", metrics());
    return { override_tx: overrideTx, action_tx: null, status: c.status };
  }
  c.hold = { ...c.hold, override_tx: overrideTx, officer_note: body.note };
  publish(c);

  await sleep(1500);
  const actionTx = randomHex(32);
  recordEvent(
    c,
    release
      ? chainEvent("Released", "compliance_escrow", actionTx, 1, {
          holdId: c.hold.hold_id,
          caseId: c.case_id_b32,
          payee: c.counterparty,
          amount: Number(c.amount),
          officer: ADDRESSES.officer,
        }, c.case_id)
      : chainEvent("Refunded", "compliance_escrow", actionTx, 1, {
          holdId: c.hold.hold_id,
          caseId: c.case_id_b32,
          payer: ADDRESSES.buyer,
          amount: Number(c.amount),
          by: ADDRESSES.officer,
        }, c.case_id),
  );
  c.hold = { ...c.hold, status: release ? "RELEASED" : "REFUNDED", action_tx: actionTx };
  c.status = release ? "RELEASED" : "REFUNDED";
  publish(c);
  emit("metrics.updated", metrics());
  return { override_tx: overrideTx, action_tx: actionTx, status: c.status };
}

function demoReset() {
  const s = getState();
  const archived = s.cases.length;
  const overrides = s.cases.filter((c) => ["RELEASED", "REFUNDED", "CLEARED", "REJECTED"].includes(c.status)).length;
  s.archived.unshift(...s.cases);
  s.cases = [];
  emit("metrics.updated", metrics());
  return { archived, overrides_cleared: overrides };
}

// ---------------------------------------------------------------- demo runs (treasury control API)

function seal(c: CaseDetail): string {
  const qs = c.checks.find((k) => k.name === "intercepta.quick_scan");
  const scan =
    qs?.status === "ok" ? `Intercepta ${qs.latency_ms} ms ${qs.live ? "live" : "cached"}` : `Intercepta ${qs?.error ?? "unavailable"}`;
  return `[SEKISHO] ${c.verdict} (score ${c.risk_score}) ${c.headline} · ${scan} · case ${c.case_id}`;
}

function vendorOf(c: CaseDetail): { id: string; name: string } {
  const port = c.resource.match(/:(\d{4})\//)?.[1] ?? "";
  return VENDORS[port] ?? { id: c.agent_id, name: c.agent_id };
}

/** Schedule one scenario's log lines and cases; returns the time it ends. */
function scheduleScenario(run: RunStatus, scenario: Scenario, t0: number): number {
  const log = (at: number, line: string | (() => string)) =>
    later(at, () => run.lines.push(typeof line === "string" ? line : line()));
  const ids = TEMPLATE_IDS[scenario];
  const first = TEMPLATES.get(ids[0]);
  if (!first) return t0;
  const vendor = vendorOf(first);
  let spawned: CaseDetail | null = null;
  const spawn = (at: number, id: string, after: (c: CaseDetail) => string) =>
    later(at, () => {
      const c = spawnFromTemplate(id);
      if (id === ids[0]) spawned = c;
      run.lines.push(after(c));
    });

  switch (scenario) {
    case "S1":
      log(t0, `[S1] Clean vendor: buying ETH/JPY data from ${vendor.id} (${vendor.name})`);
      log(t0 + 300, `[402] ${vendor.id} asks 0.05 USDC → payTo ${shortAddress(first.counterparty)}`);
      spawn(t0 + 800, ids[0], seal);
      log(t0 + 1500, "[AGENT] Signing the EIP-3009 authorisation; retrying with PAYMENT-SIGNATURE");
      if (ids[1]) spawn(t0 + 1900, ids[1], (c) => `[VENDOR] ${vendor.id} screened payer ${shortAddress(c.counterparty)}: ${c.verdict} · case ${c.case_id}`);
      log(t0 + 3600, () => `[x402] Settled on Base Sepolia: tx ${shortAddress(spawned?.payment_tx ?? null)}`);
      return t0 + 3800;
    case "S2":
    case "S6":
      if (scenario === "S6") log(t0, "[SIM] FAULT_INJECT=intercepta_timeout (Intercepta forced to time out)");
      else log(t0, `[S2] Mixer-exposed vendor: buying from ${vendor.id} (${vendor.name})`);
      log(t0 + 300, `[402] ${vendor.id} asks 0.05 USDC → payTo ${shortAddress(first.counterparty)}`);
      spawn(t0 + 800, ids[0], seal);
      log(t0 + 1400, "[AGENT] Payment aborted before signing. Depositing 0.05 USDC into ComplianceEscrow");
      log(t0 + 3900, () => `[ESCROW] Held: hold #${spawned?.hold?.hold_id ?? "?"} · tx ${shortAddress(spawned?.hold?.deposit_tx ?? null)}`);
      return t0 + 4100;
    case "S3":
      log(t0, `[S3] Sanctioned vendor: buying from ${vendor.id} (${vendor.name})`);
      log(t0 + 300, `[402] ${vendor.id} asks 0.05 USDC → payTo ${shortAddress(first.counterparty)}`);
      spawn(t0 + 800, ids[0], seal);
      log(t0 + 1300, "[AGENT] Payment refused. No signature produced.");
      return t0 + 1600;
    case "S4":
      log(t0, "[SIM] Simulating a compromised model (--assume-compromised)");
      log(t0 + 300, `[VENDOR] ${VENDORS["4024"].id} (${VENDORS["4024"].name}) returned market data with an injected note`);
      log(t0 + 700, "[AGENT] pay_invoice(0x098B…2F96, 25 USDC, INV-2291)");
      spawn(t0 + 1100, ids[0], seal);
      log(t0 + 1600, "[AGENT] Payment refused. No signature produced.");
      return t0 + 1900;
    case "S5":
      log(t0, `[SIM] Simulated spoofed payer ${shortAddress(first.counterparty)} pays ${first.agent_id}`);
      log(t0 + 300, `[VENDOR] ${first.agent_id} screening the payer before verification`);
      spawn(t0 + 800, ids[0], seal);
      log(t0 + 1300, "[VENDOR] 403 payer_refused. Nothing was verified or settled.");
      return t0 + 1600;
    default:
      return t0;
  }
}

function startRun(scenario: RunScenario): RunStarted {
  const s = getState();
  const active = s.activeRun ? s.runs.get(s.activeRun) : null;
  if (active?.status === "running") {
    throw new GateError(409, "run_in_progress", `${active.scenario} is still running. Wait for it to finish.`);
  }
  const run: RunStatus = {
    run_id: `run_${Date.now().toString(36)}`,
    scenario,
    status: "running",
    lines: [],
    started_at: isoNow(),
    finished_at: null,
  };
  s.runs.set(run.run_id, run);
  s.activeRun = run.run_id;
  const order: Scenario[] = scenario === "all" ? ["S1", "S3", "S2", "S4", "S5"] : [scenario];
  let t = 0;
  for (const sc of order) t = scheduleScenario(run, sc, t) + (scenario === "all" ? 2500 : 0);
  later(t + 200, () => {
    run.status = "succeeded";
    run.finished_at = isoNow();
    run.lines.push(`[DONE] ${scenario} finished (fixture simulation)`);
    s.activeRun = null;
  });
  return { run_id: run.run_id };
}

function control(method: Method, path: string, body: unknown): unknown {
  if (method === "POST" && path === "/run") return startRun((body as RunRequest).scenario);
  const match = path.match(/^\/runs\/([^/]+)$/);
  if (method === "GET" && match) {
    const run = getState().runs.get(decodeURIComponent(match[1]));
    if (!run) throw new GateError(404, "not_found", "No such run.");
    return clone(run);
  }
  throw new GateError(404, "not_found", `No fixture route for ${method} ${path}`);
}

// ---------------------------------------------------------------- router

export async function fixtureRequest<T>(target: Target, method: Method, path: string, body: unknown, as: BodyKind): Promise<T> {
  await sleep(90 + Math.random() * 160);
  const url = new URL(path, "http://fixtures.local");
  const p = url.pathname;
  if (target === "control") return control(method, p, body) as T;

  if (method === "GET") {
    if (p === "/v1/cases") return listCases(url.searchParams) as T;
    const caseMatch = p.match(/^\/v1\/cases\/([^/]+)$/);
    if (caseMatch) return clone(findCase(decodeURIComponent(caseMatch[1]))) as T;
    const reportMatch = p.match(/^\/v1\/reports\/([^/]+)$/);
    if (reportMatch) {
      const text = getState().reports[decodeURIComponent(reportMatch[1])];
      if (text === undefined) throw new GateError(404, "not_found", "No report with that hash.");
      return (as === "text" ? text : JSON.parse(text)) as T;
    }
    if (p === "/v1/metrics") return metrics() as T;
    if (p === "/v1/audit") return auditList(url.searchParams) as T;
    if (p === "/v1/treasury") return treasury() as T;
    if (p === "/v1/policy") return clone(policyJson as PolicyInfo) as T;
    if (p === "/v1/quota") return quota() as T;
    if (p === "/healthz") return health() as T;
  }
  if (method === "POST") {
    const decisionMatch = p.match(/^\/v1\/cases\/([^/]+)\/decision$/);
    if (decisionMatch) return (await decide(decodeURIComponent(decisionMatch[1]), body as DecisionRequest)) as T;
    if (p === "/v1/demo/reset") return demoReset() as T;
  }
  throw new GateError(404, "not_found", `No fixture route for ${method} ${p}`);
}
