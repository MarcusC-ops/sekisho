import type { ApiErrorBody } from "./types";

/** An error from the gate or the treasury control API: `{"error", "message"}` plus the HTTP status. */
export class GateError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "GateError";
    this.status = status;
    this.code = code;
  }

  static fromBody(status: number, body: Partial<ApiErrorBody> | null, fallback: string): GateError {
    return new GateError(status, body?.error || `http_${status}`, body?.message || fallback);
  }
}

/**
 * Contract reverts and officer-decision errors, in plain words (PRD 9.11 point 6).
 * The gate returns 409 with `error` set to the revert name and `message` naming the call.
 */
export const DECISION_ERRORS: Record<string, { title: string; explain: string }> = {
  NotCleared: {
    title: "Escrow refused: payee not cleared",
    explain:
      "The escrow only releases funds to a payee with a current ALLOW in the ComplianceRegistry. Record an officer override first (Release does this).",
  },
  NotHeld: {
    title: "Escrow refused: nothing is held",
    explain: "This hold was already released or refunded, so there is nothing left to move.",
  },
  PayeeBlocked: {
    title: "Escrow refused: payee is blocked",
    explain: "The ComplianceRegistry marks this payee as BLOCK, so the escrow refuses it.",
  },
  ZeroAmount: {
    title: "Escrow refused: zero amount",
    explain: "The escrow doesn't accept a hold of zero.",
  },
  NotPayer: {
    title: "Escrow refused: not the payer",
    explain: "Only the original payer can reclaim a hold without the officer role.",
  },
  TooEarly: {
    title: "Escrow refused: too early",
    explain: "The payer can reclaim a hold only after the reclaim window has passed.",
  },
  AccessControlUnauthorizedAccount: {
    title: "Contract refused: missing role",
    explain: "The signing key doesn't hold OFFICER_ROLE on this contract. Check the gate's OFFICER_PK.",
  },
  InvalidVerdict: {
    title: "Registry refused: invalid verdict",
    explain: "The ComplianceRegistry rejected the verdict value.",
  },
  InvalidTtl: {
    title: "Registry refused: invalid expiry",
    explain: "The ComplianceRegistry rejected a zero time-to-live.",
  },
  invalid_state: {
    title: "This case can't be decided now",
    explain: "Only HOLD cases in escrow (outbound) or awaiting review (inbound) can be released or refunded.",
  },
  demo_mode_only: {
    title: "Demo mode only",
    explain: "The gate allows this action only when DEMO_MODE=true.",
  },
  chain_error: {
    title: "Chain call failed",
    explain: "MultiBaas or the RPC didn't answer. Nothing was changed by this attempt; try again.",
  },
  network: {
    title: "Gate unreachable",
    explain: "The console couldn't reach the gate.",
  },
};

export function describeError(error: unknown): { code: string; title: string; message: string; explain?: string } {
  if (error instanceof GateError) {
    const known = DECISION_ERRORS[error.code];
    return {
      code: error.code,
      title: known?.title ?? `Gate error: ${error.code}`,
      message: error.message,
      explain: known?.explain,
    };
  }
  const message = error instanceof Error ? error.message : String(error);
  return { code: "unknown", title: "Something went wrong", message };
}
