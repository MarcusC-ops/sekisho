"use client";

/**
 * Applies SSE events (GET /v1/stream) to the SWR caches, so new decisions appear within a
 * second without polling. Lists respect their own filters; case detail caches merge the
 * decision and then revalidate once to pick up detail-only fields (payment_tx, evidence).
 */
import type { Cache, ScopedMutator } from "swr";
import { AUDIT_PREFIX, CASES_PREFIX, paths } from "./api";
import { announce, markFresh } from "./live";
import { shortAddress } from "./format";
import type {
  AuditPage,
  CaseDetail,
  CasesPage,
  ChainEvent,
  Metrics,
  ScreeningDecision,
  StreamEventMap,
  StreamEventName,
} from "./types";

type AnyCache = Cache<unknown>;

function cachedKeys(cache: AnyCache): string[] {
  return Array.from(cache.keys()).filter((key): key is string => typeof key === "string");
}

function params(key: string): URLSearchParams {
  const i = key.indexOf("?");
  return new URLSearchParams(i === -1 ? "" : key.slice(i + 1));
}

function matchesList(decision: ScreeningDecision, q: URLSearchParams): boolean {
  const verdict = q.get("verdict");
  const status = q.get("status");
  const direction = q.get("direction");
  return (
    (!verdict || decision.verdict === verdict) &&
    (!status || decision.status === status) &&
    (!direction || decision.direction === direction)
  );
}

const pending = new Map<string, ReturnType<typeof setTimeout>>();
/** Revalidate a key once, shortly after a burst of events. */
function revalidateSoon(mutate: ScopedMutator, key: string, delay = 350) {
  const existing = pending.get(key);
  if (existing) clearTimeout(existing);
  pending.set(
    key,
    setTimeout(() => {
      pending.delete(key);
      void mutate(key);
    }, delay),
  );
}

function applyDecision(mutate: ScopedMutator, cache: AnyCache, decision: ScreeningDecision) {
  for (const key of cachedKeys(cache)) {
    if (key.startsWith(CASES_PREFIX)) {
      const q = params(key);
      if (q.get("cursor")) {
        // Older queue pages must also stop showing holds that another officer settled.
        revalidateSoon(mutate, key);
        continue;
      }
      const limit = Number(q.get("limit") ?? 50) || 50;
      void mutate(
        key,
        (page: CasesPage | undefined) => {
          if (!page) return page;
          const index = page.items.findIndex((item) => item.case_id === decision.case_id);
          if (!matchesList(decision, q)) {
            return index === -1 ? page : { ...page, items: page.items.filter((_, i) => i !== index) };
          }
          if (index !== -1) {
            const items = page.items.slice();
            items[index] = decision;
            return { ...page, items };
          }
          const items = [decision, ...page.items]
            .sort((a, b) => Date.parse(b.decided_at) - Date.parse(a.decided_at))
            .slice(0, limit);
          return { ...page, items };
        },
        { revalidate: false },
      );
    } else if (key === paths.case(decision.case_id)) {
      void mutate(
        key,
        (detail: CaseDetail | undefined) => (detail ? { ...detail, ...decision } : detail),
        { revalidate: false },
      );
      revalidateSoon(mutate, key);
    } else if (key === paths.treasury) {
      revalidateSoon(mutate, key, 1500);
    }
  }
}

function applyChainEvent(mutate: ScopedMutator, cache: AnyCache, event: ChainEvent) {
  for (const key of cachedKeys(cache)) {
    if (key.startsWith(AUDIT_PREFIX)) {
      const q = params(key);
      const caseFilter = q.get("case_id");
      if (caseFilter && caseFilter !== event.case_id) continue;
      const limit = Number(q.get("limit") ?? 100) || 100;
      void mutate(
        key,
        (page: AuditPage | undefined) =>
          page
            ? { ...page, items: [event, ...page.items.filter((e) => e.event_uid !== event.event_uid)].slice(0, limit) }
            : page,
        { revalidate: false },
      );
    } else if (event.case_id && key === paths.case(event.case_id)) {
      void mutate(
        key,
        (detail: CaseDetail | undefined) =>
          detail
            ? { ...detail, chain_events: [...detail.chain_events.filter((e) => e.event_uid !== event.event_uid), event] }
            : detail,
        { revalidate: false },
      );
    } else if (key === paths.treasury && event.name !== "Screened") {
      revalidateSoon(mutate, key, 1500);
    }
  }
}

export function applyStreamEvent<K extends StreamEventName>(
  mutate: ScopedMutator,
  cache: AnyCache,
  event: K,
  data: StreamEventMap[K],
) {
  switch (event) {
    case "case.created": {
      const decision = data as ScreeningDecision;
      markFresh(decision.case_id);
      announce(`New decision: ${decision.verdict}, ${shortAddress(decision.counterparty)}. ${decision.headline}.`);
      applyDecision(mutate, cache, decision);
      break;
    }
    case "case.updated":
      applyDecision(mutate, cache, data as ScreeningDecision);
      break;
    case "chain.event":
      applyChainEvent(mutate, cache, data as ChainEvent);
      break;
    case "metrics.updated":
      void mutate(paths.metrics, data as Metrics, { revalidate: false });
      break;
  }
}

/** After a reconnect, refetch everything so events missed while offline are not lost. */
export function revalidateAll(mutate: ScopedMutator) {
  void mutate(() => true);
}
