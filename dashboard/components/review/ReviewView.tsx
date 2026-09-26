"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/shell/PageHeader";
import { Address } from "@/components/ui/Address";
import { Button, buttonClass } from "@/components/ui/Button";
import { DataTable } from "@/components/ui/DataTable";
import { DataState, EmptyState, Panel } from "@/components/ui/Panel";
import { awaitingDeposit, awaitingOfficer } from "@/lib/cases";
import { formatAge, formatAssetAmount, formatDateTime } from "@/lib/format";
import { useCases } from "@/lib/hooks";
import { useNow } from "@/lib/live";
import styles from "@/components/ui/data.module.css";

export function ReviewView() {
  const cursor = useSearchParams().get("cursor") || undefined;
  const query = useCases({ verdict: "HOLD", limit: 50, cursor });
  const now = useNow();
  return (
    <>
      <PageHeader title="Hold queue" lede="Review the evidence before releasing or returning held funds. Analyst recommendations are advisory."
        actions={<Button disabled={query.isValidating} onClick={() => void query.mutate()}>Refresh</Button>} />
      <Panel id="review-queue" title="Awaiting review" flush footnote="Holds are loaded in batches of 50, newest first. Completed reviews are excluded from this view.">
        <DataState {...query} onRetry={() => void query.mutate()} loadingLabel="Loading held cases">
          {(data) => {
            const pending = data.items.filter(awaitingOfficer);
            return <>
              {!pending.length ? <EmptyState title={data.next_cursor || cursor ? "No pending holds in this batch" : "No holds awaiting review"}>
                {data.next_cursor ? "Continue to older holds to check the next batch." : "New held payments will appear here when they need attention."}
              </EmptyState> : <DataTable caption="Pending held payments" headings={["Age", "Counterparty", "Amount", "Risk", "Analyst recommendation", "Next step", "Case"]}>
                {pending.map((item) => <tr key={item.case_id}>
                  <td title={formatDateTime(item.decided_at)} className={styles.nowrap}>{formatAge(item.decided_at, now)}</td>
                  <td><Address address={item.counterparty} /><p className={styles.secondary}>{item.direction === "outbound" ? "Paying →" : "← Being paid"}</p></td>
                  <td className={styles.nowrap}>{formatAssetAmount(item.amount, item.asset)}</td>
                  <td className="num">{item.risk_score} / 100</td>
                  <td>{item.analyst ? (item.analyst.officer_recommendation === "n/a" ? "No recommendation" : item.analyst.officer_recommendation === "release" ? "Release" : "Refund") : "Note pending"}
                    {item.analyst?.fallback ? <p className={styles.secondary}>Template note</p> : null}</td>
                  <td>{awaitingDeposit(item) ? "Paused; escrow not confirmed" : item.direction === "inbound" ? "Clear or reject payer" : "Release or refund"}</td>
                  <td><Link href={`/cases/${item.case_id}`} aria-label={`Open case ${item.case_id}`}>Open case</Link></td>
                </tr>)}
              </DataTable>}
              <div className={styles.toolbar} style={{ padding: "var(--space-4)" }}>
                {cursor ? <Link className={buttonClass} href="/review">Latest holds</Link> : null}
                {data.next_cursor ? <Link className={buttonClass} href={`/review?cursor=${encodeURIComponent(data.next_cursor)}`}>Older holds</Link> : null}
                <span className={styles.secondary}>{pending.length} pending in this batch</span>
              </div>
            </>;
          }}
        </DataState>
      </Panel>
    </>
  );
}
