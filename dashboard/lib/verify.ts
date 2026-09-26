/**
 * Verify report (PRD 9.7, Appendix F): fetch /v1/reports/{hash} as TEXT, hash the exact
 * served text with viem keccak256(stringToBytes(text)), and compare the result with the
 * case's report_hash AND the onchain reportHash of the case's Screened event (read from
 * the gate's audit endpoint, which comes from MultiBaas). Never re-serialise the report.
 */
import { keccak256, stringToBytes } from "viem";
import { api } from "./api";
import { latestEvent } from "./cases";
import type { CaseDetail, ChainEvent, ScreenedInputs } from "./types";

export interface VerifyOutcome {
  /** The exact text the gate served. */
  text: string;
  chars: number;
  bytes: number;
  computed: string;
  caseHash: string;
  matchesCase: boolean;
  onchain: {
    reportHash: string;
    txHash: string | null;
    explorerUrl: string | null;
    block: number | null;
    via: "audit" | "case";
  } | null;
  /** null when no Screened event is indexed yet. */
  matchesOnchain: boolean | null;
  result: "match" | "mismatch" | "partial";
}

const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

export async function verifyReport(c: CaseDetail): Promise<VerifyOutcome> {
  const text = await api.reportText(c.report_hash);
  const data = stringToBytes(text);
  const computed = keccak256(data);

  let screened: ChainEvent | undefined;
  let via: "audit" | "case" = "audit";
  try {
    const audit = await api.audit({ case_id: c.case_id, limit: 100 });
    // Newest first: the first Screened event is the latest attestation for this case.
    screened = audit.items.find((e) => e.name === "Screened" && e.case_id === c.case_id);
  } catch {
    screened = undefined;
  }
  if (!screened) {
    screened = latestEvent(c.chain_events, "Screened");
    via = "case";
  }
  const onchainHash = screened ? String((screened.inputs as ScreenedInputs).reportHash ?? "") : "";
  const onchain = screened && onchainHash
    ? {
        reportHash: onchainHash,
        txHash: screened.tx_hash,
        explorerUrl: screened.explorer_url,
        block: screened.block_number,
        via,
      }
    : null;

  const matchesCase = same(computed, c.report_hash);
  const matchesOnchain = onchain ? same(computed, onchain.reportHash) : null;
  const result = !matchesCase || matchesOnchain === false ? "mismatch" : matchesOnchain ? "match" : "partial";
  return {
    text,
    chars: text.length,
    bytes: data.length,
    computed,
    caseHash: c.report_hash,
    matchesCase,
    onchain,
    matchesOnchain,
    result,
  };
}
