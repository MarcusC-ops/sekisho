import type { Scenario, Verdict } from "./types";

/** Demo scenarios (PRD 5). Labels shown on the demo bar. */
export const SCENARIOS: {
  id: Scenario;
  name: string;
  expect: Verdict;
  direction: "outbound" | "inbound";
  /** Honesty labels the PRD requires on screen (10.3 S4, 10.4 S5). */
  label?: string;
}[] = [
  { id: "S1", name: "Clean vendor", expect: "ALLOW", direction: "outbound" },
  { id: "S2", name: "Mixer-exposed vendor", expect: "HOLD", direction: "outbound" },
  { id: "S3", name: "Sanctioned vendor", expect: "BLOCK", direction: "outbound" },
  { id: "S4", name: "Prompt injection", expect: "BLOCK", direction: "outbound", label: "Simulating a compromised model" },
  { id: "S5", name: "Tainted payer", expect: "BLOCK", direction: "inbound", label: "Simulated spoofed payer" },
  { id: "S6", name: "Fail-closed", expect: "HOLD", direction: "outbound" },
];
