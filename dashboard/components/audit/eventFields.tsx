import type { ReactNode } from "react";
import { Address } from "@/components/ui/Address";
import { VerdictChip } from "@/components/ui/Verdict";
import { formatDate, formatTokenAmount, shortHash, unixToDate } from "@/lib/format";
import { verdictFromCode } from "@/lib/vocab";
import type {
  ChainEvent,
  HeldInputs,
  RefundedInputs,
  ReleasedInputs,
  ScreenedInputs,
  VerdictOverriddenInputs,
} from "@/lib/types";

function VerdictValue({ code }: { code: unknown }) {
  const verdict = verdictFromCode(code);
  if (!verdict) return <span className="mono">{String(code)}</span>;
  if (verdict === "NONE") return <span>NONE</span>;
  return <VerdictChip verdict={verdict} />;
}

const usdc = (value: unknown) => `${formatTokenAmount(String(value ?? ""))} USDC`;
const hash = (value: unknown) => (
  <span className="mono" title={String(value ?? "")}>
    {shortHash(String(value ?? ""))}
  </span>
);

/** Decoded event inputs as label/value pairs (Solidity parameter names, PRD Appendix A). */
export function eventFields(event: ChainEvent): { label: string; value: ReactNode }[] {
  switch (event.name) {
    case "Screened": {
      const i = event.inputs as ScreenedInputs;
      const expires = unixToDate(i.expiresAt);
      return [
        { label: "Subject", value: <Address address={i.subject} /> },
        { label: "Verdict", value: <VerdictValue code={i.verdict} /> },
        { label: "Risk score", value: <span className="num">{String(i.riskScore)}</span> },
        { label: "Report hash", value: hash(i.reportHash) },
        { label: "Policy", value: hash(i.policyId) },
        { label: "Expires", value: expires ? formatDate(expires) : "—" },
        { label: "Screener", value: <Address address={i.screener} chain="payment" /> },
      ];
    }
    case "VerdictOverridden": {
      const i = event.inputs as VerdictOverriddenInputs;
      return [
        { label: "Subject", value: <Address address={i.subject} /> },
        {
          label: "Change",
          value: (
            <span style={{ display: "inline-flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
              <VerdictValue code={i.previous} /> → <VerdictValue code={i.next} />
            </span>
          ),
        },
        { label: "Note hash", value: hash(i.noteHash) },
        { label: "Officer", value: <Address address={i.officer} chain="payment" /> },
      ];
    }
    case "Held": {
      const i = event.inputs as HeldInputs;
      return [
        { label: "Hold", value: <span className="num">#{String(i.holdId)}</span> },
        { label: "Amount", value: usdc(i.amount) },
        { label: "Payer", value: <Address address={i.payer} chain="payment" /> },
        { label: "Payee", value: <Address address={i.payee} /> },
      ];
    }
    case "Released": {
      const i = event.inputs as ReleasedInputs;
      return [
        { label: "Hold", value: <span className="num">#{String(i.holdId)}</span> },
        { label: "Amount", value: usdc(i.amount) },
        { label: "Payee", value: <Address address={i.payee} /> },
        { label: "Officer", value: <Address address={i.officer} chain="payment" /> },
      ];
    }
    case "Refunded": {
      const i = event.inputs as RefundedInputs;
      return [
        { label: "Hold", value: <span className="num">#{String(i.holdId)}</span> },
        { label: "Amount", value: usdc(i.amount) },
        { label: "Payer", value: <Address address={i.payer} chain="payment" /> },
        { label: "By", value: <Address address={i.by} chain="payment" /> },
      ];
    }
    default:
      return Object.entries(event.inputs as unknown as Record<string, unknown>).map(([label, value]) => ({
        label,
        value: <span className="mono">{String(value)}</span>,
      }));
  }
}

/** A one-line summary, for compact lists. */
export function eventSummary(event: ChainEvent): string {
  switch (event.name) {
    case "Screened": {
      const i = event.inputs as ScreenedInputs;
      return `${verdictFromCode(i.verdict) ?? i.verdict} · risk ${i.riskScore}`;
    }
    case "VerdictOverridden": {
      const i = event.inputs as VerdictOverriddenInputs;
      return `${verdictFromCode(i.previous) ?? i.previous} → ${verdictFromCode(i.next) ?? i.next}`;
    }
    case "Held":
      return `Hold #${(event.inputs as HeldInputs).holdId} · ${usdc((event.inputs as HeldInputs).amount)}`;
    case "Released":
      return `Hold #${(event.inputs as ReleasedInputs).holdId} · ${usdc((event.inputs as ReleasedInputs).amount)}`;
    case "Refunded":
      return `Hold #${(event.inputs as RefundedInputs).holdId} · ${usdc((event.inputs as RefundedInputs).amount)}`;
    default:
      return event.name;
  }
}
