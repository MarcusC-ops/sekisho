"use client";

import { EmptyState, ErrorState, LoadingState } from "@/components/ui/Panel";
import { useCases } from "@/lib/hooks";
import { useAnnouncement } from "@/lib/live";
import { DecisionCard } from "./DecisionCard";
import styles from "./live.module.css";

/** Cards whose detail (for `source`) is fetched eagerly: roughly what fits on screen. */
const DETAIL_PREFETCH = 16;

export function DecisionFeed() {
  const { data, error, isLoading, mutate } = useCases({ limit: 50 });
  const announcement = useAnnouncement();
  const items = data?.items ?? [];

  return (
    <section aria-labelledby="feed-title">
      <div className={styles.feedHead}>
        <h2 id="feed-title" className={styles.feedTitle}>
          Decision feed
        </h2>
        <span className={styles.feedMeta}>
          {data ? `${items.length} ${items.length === 1 ? "decision" : "decisions"}, newest first` : "Newest first"}
        </span>
      </div>
      <p className="visually-hidden" aria-live="polite">
        {announcement}
      </p>
      {!data ? (
        <div className={styles.feedState}>
          {error ? <ErrorState error={error} onRetry={() => void mutate()} /> : isLoading ? <LoadingState label="Loading decisions" /> : null}
        </div>
      ) : items.length === 0 ? (
        <div className={styles.feedState}>
          <EmptyState title="No decisions yet. Run a scenario.">
            Use the demo controls below, or run <code>make demo S=S1</code> in a terminal.
          </EmptyState>
        </div>
      ) : (
        <>
          {error ? <ErrorState error={error} onRetry={() => void mutate()} /> : null}
          <div className={styles.feed}>
            {items.map((decision, index) => (
              <DecisionCard key={decision.case_id} decision={decision} loadDetail={index < DETAIL_PREFETCH} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
