/** Case-state rules shared by the queue, the nav badge and the officer panel (PRD 9.11). */
import type { ChainEvent, ScreeningDecision } from "./types";

/** A HOLD the officer can act on now: outbound in escrow, or inbound awaiting review. */
export function officerCanDecide(c: Pick<ScreeningDecision, "verdict" | "direction" | "status">): boolean {
  if (c.verdict !== "HOLD") return false;
  return c.direction === "outbound" ? c.status === "HELD_ESCROWED" : c.status === "DECIDED";
}

/** An outbound HOLD whose escrow deposit hasn't been reported or linked yet. */
export function awaitingDeposit(c: Pick<ScreeningDecision, "verdict" | "direction" | "status">): boolean {
  return c.verdict === "HOLD" && c.direction === "outbound" && c.status === "DECIDED";
}

/** Anything still waiting on the hold lane (deposit or officer). */
export function awaitingOfficer(c: Pick<ScreeningDecision, "verdict" | "direction" | "status">): boolean {
  return officerCanDecide(c) || awaitingDeposit(c);
}

export function latestEvent(events: ChainEvent[] | undefined, name: ChainEvent["name"]): ChainEvent | undefined {
  if (!events) return undefined;
  for (let i = events.length - 1; i >= 0; i -= 1) if (events[i].name === name) return events[i];
  return undefined;
}
