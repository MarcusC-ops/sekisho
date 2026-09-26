/** Display vocabulary for enums and names in the contract (one place, so wording stays consistent). */
import type {
  CaseStatus,
  CheckName,
  ChainEventName,
  Direction,
  ReasonSource,
  Source,
  TraitClass,
  Verdict,
} from "./types";

export const VERDICT_META: Record<
  Verdict,
  { label: string; kanji: string; kanjiGloss: string; tone: "allow" | "hold" | "block"; meaning: string }
> = {
  ALLOW: { label: "ALLOW", kanji: "通", kanjiGloss: "pass", tone: "allow", meaning: "Payment may proceed" },
  HOLD: { label: "HOLD", kanji: "留", kanjiGloss: "hold", tone: "hold", meaning: "Held for a compliance officer" },
  BLOCK: { label: "BLOCK", kanji: "止", kanjiGloss: "stop", tone: "block", meaning: "Refused. Nothing is signed" },
};

/** ComplianceRegistry.Verdict enum (Appendix A). */
export const VERDICT_BY_CODE: Record<number, Verdict | "NONE"> = { 0: "NONE", 1: "ALLOW", 2: "HOLD", 3: "BLOCK" };

export function verdictFromCode(value: unknown): Verdict | "NONE" | null {
  const n = Number(value);
  return Number.isInteger(n) && n in VERDICT_BY_CODE ? VERDICT_BY_CODE[n] : null;
}

export const STATUS_LABEL: Record<CaseStatus, string> = {
  DECIDED: "Decided",
  PAID: "Paid",
  HELD_ESCROWED: "In escrow",
  RELEASED: "Released",
  REFUNDED: "Refunded",
  CLEARED: "Payer cleared",
  REJECTED: "Payer rejected",
  REFUSED: "Refused",
};

export const DIRECTION_LABEL: Record<Direction, string> = {
  outbound: "paying",
  inbound: "being paid",
};

export const DIRECTION_HELP: Record<Direction, string> = {
  outbound: "Our agent pays this counterparty",
  inbound: "This counterparty pays our agent",
};

export const SOURCE_LABEL: Record<Source, string> = {
  x402: "x402",
  mcp: "MCP",
  direct: "direct",
};

export const CHECK_TITLE: Record<CheckName, string> = {
  "intercepta.quick_scan": "Intercepta Quick Scan",
  "sanctions.oracle": "Chainalysis sanctions oracle",
  "trace.source_of_funds": "Source-of-funds trace",
  "intercepta.impersonation": "Intercepta impersonation check",
  "intercepta.token": "Intercepta token scan",
  "intercepta.deep_scan": "Intercepta Deep Scan",
};

export function checkTitle(name: string): string {
  return CHECK_TITLE[name as CheckName] ?? name;
}

export const REASON_SOURCE_LABEL: Record<ReasonSource, string> = {
  chainalysis: "Chainalysis",
  intercepta: "Intercepta",
  trace: "Source of funds",
  policy: "Policy",
  officer: "Officer",
};

export const TRAIT_CLASS_LABEL: Record<TraitClass, string> = {
  hard_block: "Hard block",
  hold: "Hold",
  info: "Info only",
  other: "Other",
};

export const EVENT_LABEL: Record<ChainEventName, string> = {
  Screened: "Screened",
  VerdictOverridden: "Verdict overridden",
  Held: "Held in escrow",
  Released: "Released",
  Refunded: "Refunded",
};

/** Where each evidence id points on the case page (gate/sekisho_gate/checks.py). */
export const EVIDENCE_ANCHOR: Record<string, { anchor: string; label: string }> = {
  E1: { anchor: "evidence-quick-scan", label: "Intercepta Quick Scan" },
  E2: { anchor: "evidence-oracle", label: "Sanctions oracle" },
  E3: { anchor: "source-of-funds", label: "Source of funds" },
  E4: { anchor: "evidence-impersonation", label: "Impersonation check" },
  E5: { anchor: "evidence-token", label: "Token scan" },
  E6: { anchor: "evidence-deep-scan", label: "Deep Scan" },
};
