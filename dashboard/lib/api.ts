/**
 * The console's only data client. It talks to the gate (NEXT_PUBLIC_GATE_URL) and the
 * treasury control API, or, when NEXT_PUBLIC_USE_FIXTURES=true, to an in-browser
 * simulation of both built from dashboard/fixtures. SWR keys are the request paths.
 */
import { GATE_URL, TREASURY_CONTROL_URL, USE_FIXTURES } from "./config";
import { GateError } from "./errors";
import { operatorHeaders } from "./operator-session";
import type {
  AuditPage,
  CaseDetail,
  CasesPage,
  CasesQuery,
  DecisionRequest,
  DecisionResponse,
  DemoResetResponse,
  Health,
  Metrics,
  PolicyInfo,
  Quota,
  RunScenario,
  RunStarted,
  RunStatus,
  Treasury,
} from "./types";

export type Target = "gate" | "control";
export type Method = "GET" | "POST";
export type BodyKind = "json" | "text";

async function send<T>(target: Target, method: Method, path: string, body?: unknown, as: BodyKind = "json"): Promise<T> {
  if (USE_FIXTURES) {
    const fixtures = await import("./fixtures/server");
    return fixtures.fixtureRequest<T>(target, method, path, body, as);
  }
  const base = target === "gate" ? GATE_URL : TREASURY_CONTROL_URL;
  let res: Response;
  try {
    res = await fetch(`${base}${path}`, {
      method,
      cache: "no-store",
      headers: {
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(method === "POST" ? operatorHeaders() : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new GateError(
      0,
      "network",
      target === "gate"
        ? `Can't reach the gate at ${GATE_URL}. Check that it's running (make gate).`
        : `Can't reach the treasury control API at ${TREASURY_CONTROL_URL}. Start it, or run scenarios from the terminal.`,
    );
  }
  if (!res.ok) {
    let parsed: { error?: string; message?: string } | null = null;
    try {
      parsed = (await res.json()) as { error?: string; message?: string };
    } catch {
      parsed = null;
    }
    throw GateError.fromBody(res.status, parsed, res.statusText || `HTTP ${res.status}`);
  }
  // The report endpoint must be read as TEXT: Verify hashes the exact served bytes.
  return (as === "text" ? await res.text() : await res.json()) as T;
}

/** SWR fetcher for gate GET paths. */
export function fetchGate<T>(path: string): Promise<T> {
  return send<T>("gate", "GET", path);
}

function query(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") q.set(key, String(value));
  }
  const text = q.toString();
  return text ? `?${text}` : "";
}

/** Request paths, which double as SWR cache keys. Keep param order stable. */
export const paths = {
  cases: (q: CasesQuery = {}) =>
    `/v1/cases${query({ verdict: q.verdict, status: q.status, direction: q.direction, limit: q.limit ?? 50, cursor: q.cursor })}`,
  case: (caseId: string) => `/v1/cases/${encodeURIComponent(caseId)}`,
  report: (reportHash: string) => `/v1/reports/${encodeURIComponent(reportHash)}`,
  metrics: "/v1/metrics",
  audit: (q: { limit?: number; case_id?: string } = {}) => `/v1/audit${query({ limit: q.limit ?? 100, case_id: q.case_id })}`,
  treasury: "/v1/treasury",
  policy: "/v1/policy",
  quota: "/v1/quota",
  health: "/healthz",
} as const;

export const CASES_PREFIX = "/v1/cases?";
export const CASE_PREFIX = "/v1/cases/";
export const AUDIT_PREFIX = "/v1/audit";

export const api = {
  cases: (q?: CasesQuery) => fetchGate<CasesPage>(paths.cases(q)),
  case: (caseId: string) => fetchGate<CaseDetail>(paths.case(caseId)),
  /** The exact canonical bytes, as text. Never parse and re-serialise before hashing. */
  reportText: (reportHash: string) => send<string>("gate", "GET", paths.report(reportHash), undefined, "text"),
  metrics: () => fetchGate<Metrics>(paths.metrics),
  audit: (q?: { limit?: number; case_id?: string }) => fetchGate<AuditPage>(paths.audit(q)),
  treasury: () => fetchGate<Treasury>(paths.treasury),
  policy: () => fetchGate<PolicyInfo>(paths.policy),
  quota: () => fetchGate<Quota>(paths.quota),
  health: () => fetchGate<Health>(paths.health),
  decide: (caseId: string, body: DecisionRequest) =>
    send<DecisionResponse>("gate", "POST", `${paths.case(caseId)}/decision`, body),
  demoReset: () => send<DemoResetResponse>("gate", "POST", "/v1/demo/reset", {}),
  control: {
    run: (scenario: RunScenario) => send<RunStarted>("control", "POST", "/run", { scenario }),
    getRun: (runId: string) => send<RunStatus>("control", "GET", `/runs/${encodeURIComponent(runId)}`),
  },
};
