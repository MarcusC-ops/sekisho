"use client";

import Link from "next/link";
import { eventSummary } from "@/components/audit/eventFields";
import { Icon } from "@/components/ui/Icon";
import { Panel } from "@/components/ui/Panel";
import { TxLink } from "@/components/ui/Address";
import { awaitingOfficer, officerCanDecide } from "@/lib/cases";
import { formatAge, formatAssetAmount, shortAddress } from "@/lib/format";
import { useAudit, useHoldCases } from "@/lib/hooks";
import { useNow } from "@/lib/live";
import { EVENT_LABEL } from "@/lib/vocab";
import styles from "./live.module.css";

function HoldPreview() {
  const { data, error } = useHoldCases();
  const now = useNow();
  const waiting = (data?.items ?? []).filter(awaitingOfficer);
  return (
    <Panel
      eyebrow="Human review"
      title="Awaiting an officer"
      flush
      actions={
        <Link href="/review" className="mono" style={{ fontSize: "var(--text-sm)" }}>
          Open queue
        </Link>
      }
    >
      {error && !data ? (
        <p className={styles.railEmpty}>Hold queue unavailable.</p>
      ) : !data ? (
        <p className={styles.railEmpty}>Loading…</p>
      ) : waiting.length === 0 ? (
        <p className={styles.railEmpty}>Nothing is waiting for review.</p>
      ) : (
        <ul className={styles.railList}>
          {waiting.slice(0, 5).map((c) => (
            <li key={c.case_id} className={styles.railItem} data-tone="hold">
              <span className={styles.railIcon}>
                <Icon name={officerCanDecide(c) ? "hold" : "escrow"} size={20} strokeWidth={2.2} />
              </span>
              <span className={styles.railMain}>
                <Link href={`/cases/${encodeURIComponent(c.case_id)}`} className={styles.railTitle}>
                  {shortAddress(c.counterparty)} · {formatAssetAmount(c.amount, c.asset)}
                </Link>
                <span className={styles.railMeta}>
                  {officerCanDecide(c) ? c.headline : "Signing paused · no confirmed escrow deposit"}
                </span>
              </span>
              <span className={styles.railMeta}>{formatAge(c.decided_at, now)}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function RecentEvents() {
  const { data, error } = useAudit({ limit: 6 });
  return (
    <Panel
      eyebrow="Indexed by Curvegrid MultiBaas"
      title="Latest onchain events"
      flush
      actions={
        <Link href="/audit" className="mono" style={{ fontSize: "var(--text-sm)" }}>
          Audit log
        </Link>
      }
    >
      {error && !data ? (
        <p className={styles.railEmpty}>Audit log unavailable.</p>
      ) : !data ? (
        <p className={styles.railEmpty}>Loading…</p>
      ) : data.items.length === 0 ? (
        <p className={styles.railEmpty}>No contract events yet.</p>
      ) : (
        <ul className={styles.railList}>
          {data.items.map((e) => (
            <li key={e.event_uid} className={styles.railItem}>
              <span className={styles.railIcon}>
                <Icon name={e.name === "Screened" ? "shield" : e.name === "VerdictOverridden" ? "officer" : "escrow"} size={20} />
              </span>
              <span className={styles.railMain}>
                <span className={styles.railTitle}>{EVENT_LABEL[e.name] ?? e.name}</span>
                <span className={styles.railMeta}>{eventSummary(e)}</span>
              </span>
              <TxLink hash={e.tx_hash} url={e.explorer_url} />
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function LiveRail() {
  return (
    <aside className={styles.rail} aria-label="Queue and onchain activity">
      <HoldPreview />
      <RecentEvents />
    </aside>
  );
}
