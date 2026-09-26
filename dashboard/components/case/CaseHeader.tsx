import { Address, CopyButton } from "@/components/ui/Address";
import { DirectionLabel, SourceTag, StatusChip } from "@/components/ui/Pills";
import { VerdictSeal, verdictTone } from "@/components/ui/Verdict";
import { formatAssetAmount, formatDateTime, formatMs } from "@/lib/format";
import type { CaseDetail } from "@/lib/types";
import styles from "./case.module.css";

/** A 0 to 100 arc. The score comes from the policy (PRD 9.6), not from the verdict thresholds. */
export function RiskGauge({ score, tone }: { score: number; tone: string }) {
  const value = Math.max(0, Math.min(100, Math.round(score)));
  return (
    <div className={styles.gauge} data-tone={tone}>
      <svg
        className={styles.gaugeSvg}
        width="150"
        height="88"
        viewBox="0 0 150 88"
        role="img"
        aria-label={`Risk score ${value} out of 100`}
      >
        <path className={styles.gaugeTrack} d="M 13 80 A 62 62 0 0 1 137 80" fill="none" strokeWidth="14" strokeLinecap="round" />
        <path
          className={styles.gaugeValue}
          d="M 13 80 A 62 62 0 0 1 137 80"
          fill="none"
          strokeWidth="14"
          strokeLinecap="round"
          pathLength={100}
          strokeDasharray={`${value} 100`}
        />
        <text className={styles.gaugeNumber} x="75" y="78" textAnchor="middle">
          {value}
        </text>
      </svg>
      <span className={styles.gaugeLabel}>Risk score, 0 to 100</span>
    </div>
  );
}

export function CaseHeader({ c, stamp }: { c: CaseDetail; stamp: boolean }) {
  const tone = verdictTone(c.verdict);
  return (
    <header className={styles.header}>
      <VerdictSeal verdict={c.verdict} stamp={stamp} />
      <div className={styles.headerMain}>
        <h1 className={styles.headline}>{c.headline}</h1>
        <div className={styles.metaRow}>
          <DirectionLabel direction={c.direction} />
          <Address address={c.counterparty} />
          <span className={styles.amountBig}>{formatAssetAmount(c.amount, c.asset)}</span>
          <SourceTag source={c.source} />
          <StatusChip status={c.status} />
        </div>
        <div className={styles.metaRow}>
          <span className={styles.metaText}>
            <time dateTime={c.decided_at} title={c.decided_at}>
              {formatDateTime(c.decided_at)}
            </time>{" "}
            · verdict in <strong>{formatMs(c.latency_ms)}</strong> · agent <strong>{c.agent_id || "—"}</strong>
          </span>
          <span className={styles.caseId} title="Case id">
            {c.case_id}
            <CopyButton value={c.case_id} label="Copy case id" />
          </span>
        </div>
      </div>
      <RiskGauge score={c.risk_score} tone={tone} />
    </header>
  );
}
