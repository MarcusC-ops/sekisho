"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/shell/PageHeader";
import { Address } from "@/components/ui/Address";
import { Button, buttonClass } from "@/components/ui/Button";
import { DataTable } from "@/components/ui/DataTable";
import { Meter } from "@/components/ui/Meter";
import { DataState, EmptyState, Panel } from "@/components/ui/Panel";
import { VerdictChip } from "@/components/ui/Verdict";
import { formatDateTime, formatUsd, shortAddress } from "@/lib/format";
import { useTreasury } from "@/lib/hooks";
import type { PayeeTotal } from "@/lib/types";
import styles from "@/components/ui/data.module.css";

function PayeeBars({ rows, label }: { rows: PayeeTotal[] | null; label: string }) {
  if (rows === null) return <EmptyState title="Event Query unavailable">The gate could not read these totals. Check the dependency errors above and retry.</EmptyState>;
  if (!rows.length) return <EmptyState title="No indexed movements yet">Totals will appear when escrow events are indexed.</EmptyState>;
  const sorted = [...rows].sort((a, b) => b.total_usd - a.total_usd);
  const max = Math.max(...sorted.map((row) => row.total_usd), 0.01);
  return <div className={styles.bars}>
    {sorted.slice(0, 20).map((row) => <div key={row.payee}>
      <div className={styles.barHead}><Address address={row.payee} /><strong className="num">{formatUsd(row.total_usd)}</strong></div>
      <Meter value={row.total_usd} max={max} label={`${label} for ${shortAddress(row.payee)} in USD`} />
    </div>)}
    {rows.length > 20 ? <p className={styles.secondary}>Showing the 20 largest totals of {rows.length} payees.</p> : null}
  </div>;
}

export function TreasuryView() {
  const query = useTreasury();
  const pageValue = Number(useSearchParams().get("page") || "1");
  const requestedPage = Number.isSafeInteger(pageValue) && pageValue > 0 ? pageValue : 1;
  return <div className={styles.stack}>
    <PageHeader title="Treasury" lede="Track the agent’s USDC, held funds, and counterparties across payment decisions."
      actions={<Button disabled={query.isValidating} onClick={() => void query.mutate()}>Refresh</Button>} />
    <DataState {...query} loadingLabel="Loading treasury" onRetry={() => void query.mutate()}>
      {(data) => {
        const book = data.counterparty_book;
        const pages = Math.max(1, Math.ceil((book?.length ?? 0) / 20));
        const page = Math.min(requestedPage, pages);
        return <>
          {data.errors.length ? <div className={styles.notice} role="alert"><strong>Some treasury data is unavailable</strong>
            <p>Unavailable values are shown as —, not as zero.</p><ul>{data.errors.map((error, i) => <li key={i}>{error}</li>)}</ul></div> : null}
          <dl className={styles.stats}>
            <div className={styles.stat}><dt>Treasury Agent USDC</dt><dd>{formatUsd(data.buyer_usdc_usd)}</dd><div className={styles.secondary}><Address address={data.buyer_address} chain="payment" /></div></div>
            <div className={styles.stat}><dt>In escrow</dt><dd>{formatUsd(data.escrow_total_held_usd)}</dd><div className={styles.secondary}><Address address={data.escrow_address} chain="payment" /></div></div>
            <div className={styles.stat}><dt>Paid via x402</dt><dd>{formatUsd(data.paid_via_x402_usd)}</dd><p className={styles.secondary}>Recorded payments since reset</p></div>
            <div className={styles.stat}><dt>Value blocked</dt><dd>{formatUsd(data.value_blocked_usd)}</dd><p className={styles.secondary}>Blocked payment intents since reset</p></div>
          </dl>
          <p className={styles.secondary}>Powered by Curvegrid MultiBaas Event Queries. Chain data cached at {formatDateTime(data.cached_at)}; refreshed by the gate every 60 seconds.</p>
          <div className={styles.columns}>
            <Panel id="exposure" title="Exposure by payee" footnote="Cumulative Held events across indexed history, including funds later released or refunded. Current outstanding funds are shown in the escrow balance above.">
              <PayeeBars rows={data.exposure_by_payee} label="Cumulative deposits" />
            </Panel>
            <Panel id="released" title="Released by payee" footnote="Cumulative Released events across indexed history.">
              <PayeeBars rows={data.released_by_payee} label="Released" />
            </Panel>
          </div>
          <Panel id="counterparties" title="Counterparty book" flush footnote="Latest screening verdict and recorded payments since reset. A historical ALLOW is not clearance for a new payment; screen again before signing.">
            {book === null ? <EmptyState title="Counterparty book unavailable" /> : !book.length ? <EmptyState title="No counterparties screened yet">Run a payment scenario to start building the book.</EmptyState> : <>
              <DataTable caption="Counterparty screening and payment history" headings={["Counterparty", "Latest verdict", "Last screened", "Paid", "Held", "Cases"]}>
                {book.slice((page - 1) * 20, page * 20).map((item) => <tr key={item.counterparty}>
                  <td><Address address={item.counterparty} /></td><td><VerdictChip verdict={item.latest_verdict} /></td>
                  <td>{formatDateTime(item.last_screened_at)}</td><td>{formatUsd(item.total_paid_usd)}</td>
                  <td>{formatUsd(item.total_held_usd)}</td><td>{item.cases}</td>
                </tr>)}
              </DataTable>
              <nav className={styles.toolbar} aria-label="Counterparty pages" style={{ padding: "var(--space-4)" }}>
                {page > 1 ? <Link className={buttonClass} href={`/treasury?page=${page - 1}#counterparties`}>Previous</Link> : null}
                <span>Page {page} of {pages} · {book.length} counterparties</span>
                {page < pages ? <Link className={buttonClass} href={`/treasury?page=${page + 1}#counterparties`}>Next</Link> : null}
              </nav>
            </>}
          </Panel>
        </>;
      }}
    </DataState>
  </div>;
}
