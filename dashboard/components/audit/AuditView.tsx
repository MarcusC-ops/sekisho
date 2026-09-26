"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/shell/PageHeader";
import { TxLink } from "@/components/ui/Address";
import { Button } from "@/components/ui/Button";
import { DataTable } from "@/components/ui/DataTable";
import { DataState, EmptyState, Panel } from "@/components/ui/Panel";
import { formatDateTime, formatInt } from "@/lib/format";
import { useAudit } from "@/lib/hooks";
import { eventFields, eventSummary } from "./eventFields";
import styles from "@/components/ui/data.module.css";

const EVENTS = ["All", "Screened", "VerdictOverridden", "Held", "Released", "Refunded"];

export function AuditView() {
  const params = useSearchParams();
  const selected = EVENTS.includes(params.get("event") || "") ? params.get("event")! : "All";
  const caseId = params.get("case_id") || undefined;
  const query = useAudit({ limit: 100, case_id: caseId });
  const filterUrl = (event: string) => {
    const next = new URLSearchParams();
    if (caseId) next.set("case_id", caseId);
    if (event !== "All") next.set("event", event);
    return `/audit${next.size ? `?${next}` : ""}`;
  };
  return <div className={styles.stack}>
    <PageHeader title="Onchain audit log" lede="Follow screenings, officer overrides, and escrow movements. Open a case to verify its evidence against the attested report hash."
      actions={<Button disabled={query.isValidating} onClick={() => void query.mutate()}>Refresh</Button>} />
    <nav className={styles.filters} aria-label="Filter audit events">{EVENTS.map((event) =>
      <Link key={event} href={filterUrl(event)} aria-current={selected === event ? "page" : undefined}>{event === "VerdictOverridden" ? "Overrides" : event}</Link>)}</nav>
    {caseId ? <p>Events for <span className="mono">{caseId}</span>. <Link href="/audit">Show all cases</Link></p> : null}
    <Panel id="audit-events" title="Contract events" flush footnote="Indexed by Curvegrid MultiBaas. This view filters the latest 100 events; times show when the gate received each event.">
      <DataState {...query} loadingLabel="Loading onchain events" onRetry={() => void query.mutate()}>
        {(data) => {
          const items = data.items.filter((event) => selected === "All" || event.name === selected);
          return !items.length ? <EmptyState title={data.items.length ? "No matching events in this window" : "No onchain events received yet"}>
            {data.items.length ? <Link href={filterUrl("All")}>Show all event types</Link> : "Confirmed screenings and escrow transactions will appear after the gate receives their events."}
          </EmptyState> : <DataTable caption="Latest onchain audit events" headings={["Received", "Event and decoded fields", "Block", "Transaction", "Case"]}>
            {items.map((event) => <tr key={event.event_uid}>
              <td>{formatDateTime(event.received_at)}</td>
              <td><strong>{event.name}</strong><p className={styles.secondary}>{eventSummary(event)}</p>
                <details className={styles.disclosure}><summary>Decoded fields</summary><dl className={styles.fields}>
                  {eventFields(event).map((field) => <div key={field.label}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}
                </dl></details></td>
              <td className="num">{formatInt(event.block_number)}</td>
              <td><TxLink hash={event.tx_hash} url={event.explorer_url} /></td>
              <td>{event.case_id ? <Link href={`/cases/${event.case_id}`} aria-label={`Open case ${event.case_id}`}>Open case</Link> : <span className={styles.secondary}>Unlinked event</span>}</td>
            </tr>)}
          </DataTable>;
        }}
      </DataState>
    </Panel>
  </div>;
}
