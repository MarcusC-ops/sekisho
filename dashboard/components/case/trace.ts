/** Flag severity for source-of-funds hops (PRD 9.5 flags). */
const HARD_TRAITS = ["sanction_address", "known_scammer", "initiator_scam_transactions", "blacklist"];

export type FlagTone = "block" | "hold";

export function flagTone(flag: string): FlagTone {
  if (flag === "sanctioned") return "block";
  if (flag.startsWith("intercepta:") && HARD_TRAITS.includes(flag.slice("intercepta:".length))) return "block";
  return "hold";
}

/** The strongest flag on a hop, or null if unflagged. */
export function hopTone(flags: string[] | undefined): FlagTone | null {
  if (!flags?.length) return null;
  return flags.some((f) => flagTone(f) === "block") ? "block" : "hold";
}
