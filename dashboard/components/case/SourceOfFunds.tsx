"use client";

import dynamic from "next/dynamic";
import { Address } from "@/components/ui/Address";
import { Icon } from "@/components/ui/Icon";
import { Meter } from "@/components/ui/Meter";
import { Panel } from "@/components/ui/Panel";
import { LiveTag } from "@/components/ui/Pills";
import { chainName } from "@/lib/config";
import { formatMs, formatPct, formatUsd, shortAddress } from "@/lib/format";
import { usePolicy } from "@/lib/hooks";
import type { CaseDetail } from "@/lib/types";
import styles from "./case.module.css";
import { flagTone, hopTone } from "./trace";

const TraceGraph = dynamic(() => import("./TraceGraph"), {
  ssr: false,
  loading: () => <p className="visually-hidden">Loading the funds graph</p>,
});

function Flags({ flags }: { flags: string[] }) {
  if (!flags.length) return <span className={styles.muted}>—</span>;
  return (
    <>
      {flags.map((f) => (
        <span key={f} className={styles.flag} data-tone={flagTone(f)}>
          {f}
        </span>
      ))}
    </>
  );
}

export function SourceOfFunds({ c }: { c: CaseDetail }) {
  const { data: policy } = usePolicy();
  const trace = c.trace;
  const check = c.checks.find((k) => k.name === "trace.source_of_funds");
  const holdPct = policy?.parsed.thresholds?.taint_hold_pct ?? 10;
  const blockPct = policy?.parsed.thresholds?.taint_block_pct ?? 50;

  const actions = check ? (
    <span className={styles.subheadMeta} style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
      <LiveTag live={check.live} />
      {formatMs(check.latency_ms)} · {check.evidence_id ?? "E3"}
    </span>
  ) : null;

  if (!trace) {
    return (
      <Panel id="source-of-funds" eyebrow="Where the money came from" title="Source of funds" actions={actions}>
        <div className={styles.revert} role="note">
          <span className={styles.revertTitle}>
            <Icon name="error" size={18} />
            Trace unavailable{check?.error ? `: ${check.error}` : ""}
          </span>
          <span>The taint rules couldn&apos;t run for this decision. The other checks still ran and decided the verdict.</span>
        </div>
      </Panel>
    );
  }

  const flagged = trace.hop1.filter((h) => h.flags.length).length;
  const taintTone = trace.taint_pct >= blockPct ? "block" : trace.taint_pct >= holdPct ? "hold" : null;
  const fill = taintTone ? `var(--verdict-${taintTone}-mark)` : undefined;

  return (
    <Panel id="source-of-funds" eyebrow="Where the money came from" title="Source of funds" actions={actions}>
      <div className={styles.taint}>
        <div className={styles.taintFigure}>
          <span className={styles.taintNumber}>{formatPct(trace.taint_pct)}</span>
          <span className={styles.muted}>taint</span>
        </div>
        <div className={styles.taintMeter}>
          <span>
            Share of traced inbound value from flagged sources. Traced <strong>{formatUsd(trace.inbound_usd_traced)}</strong> on{" "}
            {trace.chains.map((id) => chainName(id)).join(" and ")} · {trace.hop1.length} direct{" "}
            {trace.hop1.length === 1 ? "funder" : "funders"}
            {flagged ? `, ${flagged} flagged` : ""}.
          </span>
          <Meter
            value={trace.taint_pct}
            max={100}
            fill={fill}
            label={`Taint ${trace.taint_pct}%`}
            ticks={[
              { at: holdPct, label: `Hold at ${holdPct}%` },
              { at: blockPct, label: `Block at ${blockPct}%` },
            ]}
          />
          <div className={styles.taintTicks} aria-hidden="true">
            <span className={styles.taintTick} style={{ left: `${holdPct}%` }}>
              hold {holdPct}%
            </span>
            <span className={styles.taintTick} style={{ left: `${blockPct}%` }}>
              block {blockPct}%
            </span>
          </div>
        </div>
      </div>

      {trace.hop1.length ? (
        <div className={styles.graphWrap} aria-label="Funds graph: direct funders around the counterparty">
          <TraceGraph trace={trace} counterparty={c.counterparty} />
        </div>
      ) : null}

      {trace.hop1.length ? (
        <>
          <h3 className={styles.subhead}>Direct funders (hop 1)</h3>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Funder</th>
                  <th scope="col">Labels</th>
                  <th scope="col" className={styles.num}>
                    USD
                  </th>
                  <th scope="col" className={styles.num}>
                    Share
                  </th>
                  <th scope="col" className={styles.num}>
                    Txs
                  </th>
                  <th scope="col">Flags</th>
                </tr>
              </thead>
              <tbody>
                {trace.hop1.map((h) => {
                  const tone = hopTone(h.flags);
                  return (
                    <tr key={`${h.chain_id}:${h.address}`} className={tone ? styles.rowFlagged : undefined} data-tone={tone ?? undefined}>
                      <td>
                        <Address address={h.address} chain={h.chain_id} />
                        <div className={styles.muted}>{chainName(h.chain_id)}</div>
                      </td>
                      <td>{h.labels.length ? h.labels.join(", ") : <span className={styles.muted}>No public label</span>}</td>
                      <td className={styles.num}>{formatUsd(h.usd)}</td>
                      <td className={styles.num}>
                        <span className={styles.shareCell}>
                          <span>{formatPct(h.share_pct)}</span>
                          <span className={styles.shareBar} aria-hidden="true">
                            <span className={styles.shareFill} style={{ display: "block", width: `${Math.min(100, h.share_pct ?? 0)}%` }} />
                          </span>
                        </span>
                      </td>
                      <td className={styles.num}>{h.tx_count}</td>
                      <td>
                        <Flags flags={h.flags} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className={styles.muted}>No inbound transfers were found for this address on the traced chains.</p>
      )}

      {trace.hop2.length ? (
        <>
          <h3 className={styles.subhead} style={{ marginTop: "var(--space-5)" }}>
            Second hop <span className={styles.subheadMeta}>oracle and public labels only</span>
          </h3>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Via</th>
                  <th scope="col">Funder</th>
                  <th scope="col" className={styles.num}>
                    USD
                  </th>
                  <th scope="col">Flags</th>
                </tr>
              </thead>
              <tbody>
                {trace.hop2.map((h) => {
                  const tone = hopTone(h.flags);
                  return (
                    <tr key={`${h.via}:${h.address}`} className={tone ? styles.rowFlagged : undefined} data-tone={tone ?? undefined}>
                      <td className="mono">{shortAddress(h.via)}</td>
                      <td>
                        <Address address={h.address} chain={h.chain_id} />
                      </td>
                      <td className={styles.num}>{formatUsd(h.usd)}</td>
                      <td>
                        <Flags flags={h.flags} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {trace.paths.length ? (
        <>
          <h3 className={styles.subhead} style={{ marginTop: "var(--space-5)" }}>
            Flagged paths
          </h3>
          <ul className={styles.paths}>
            {trace.paths.map((p) => (
              <li key={p} className={styles.path} data-tone={taintTone ?? "hold"}>
                <Icon name="flag" size={16} />
                <span>{p}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <div className={styles.notes}>
        {trace.truncated ? <span>Partial trace: first page of inbound transfers only.</span> : null}
        {trace.notes.map((note) => (
          <span key={note}>{note.includes("ETH_USD_PRICE") ? `${note} (a demo approximation)` : note}</span>
        ))}
      </div>
    </Panel>
  );
}
