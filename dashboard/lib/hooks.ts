"use client";

import useSWR, { type SWRConfiguration } from "swr";
import { fetchGate, paths } from "./api";
import type {
  AuditPage,
  CaseDetail,
  CasesPage,
  CasesQuery,
  Health,
  Metrics,
  PolicyInfo,
  Treasury,
} from "./types";

export function useCases(query?: CasesQuery) {
  return useSWR<CasesPage>(paths.cases(query), fetchGate);
}

export function useCaseDetail(caseId: string | null | undefined) {
  return useSWR<CaseDetail>(caseId ? paths.case(caseId) : null, fetchGate);
}

export function useMetrics() {
  return useSWR<Metrics>(paths.metrics, fetchGate);
}

export function useAudit(query?: { limit?: number; case_id?: string }) {
  return useSWR<AuditPage>(paths.audit(query), fetchGate);
}

export function useTreasury() {
  return useSWR<Treasury>(paths.treasury, fetchGate, { refreshInterval: 60_000 });
}

export function usePolicy() {
  return useSWR<PolicyInfo>(paths.policy, fetchGate, { revalidateOnFocus: false });
}

const HEALTH_OPTIONS: SWRConfiguration = { refreshInterval: 30_000 };

/** Gate dependency status and DEMO_MODE (always 200 from the gate). */
export function useHealth() {
  return useSWR<Health>(paths.health, fetchGate, HEALTH_OPTIONS);
}

/** Every HOLD case, for the review queue and the nav badge. */
export function useHoldCases() {
  return useCases({ verdict: "HOLD", limit: 100 });
}
