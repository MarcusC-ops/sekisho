"use client";

import Link from "next/link";
import { useState } from "react";
import { Address } from "@/components/ui/Address";
import { Icon } from "@/components/ui/Icon";
import { AttestationPill, DirectionLabel, SourceTag, StatusChip } from "@/components/ui/Pills";
import { ReasonText, sortReasons } from "@/components/ui/Reason";
import { VerdictChip, verdictTone } from "@/components/ui/Verdict";
import { formatAgo, formatAssetAmount, formatClock, formatMs } from "@/lib/format";
import { useCaseDetail } from "@/lib/hooks";
import { isFresh, useNow } from "@/lib/live";
import type { ScreeningDecision } from "@/lib/types";
import styles from "./live.module.css";

/**
 * One decision in the live feed. The whole card opens the case (stretched link); the
 * copy, explorer and attestation links sit above it. `source` lives on CaseDetail only,
 * so the card reads it from the (shared, cached) case detail.
 */
export function DecisionCard({ decision, loadDetail = true }: { decision: ScreeningDecision; loadDetail?: boolean }) {
  const [fresh] = useState(() => isFresh(decision.case_id));
  const now = useNow();
  const { data: detail } = useCaseDetail(loadDetail ? decision.case_id : null);
  const reasons = sortReasons(decision.reasons).slice(0, 2);
  const tone = verdictTone(decision.verdict);

  return (
    <article className={styles.card} data-tone={tone} data-fresh={fresh || undefined}>
      <div className={styles.cardRail} aria-hidden="true" />
      <div className={styles.cardBody}>
        <div className={styles.cardTop}>
          <span className={styles.stampOnArrive}>
            <VerdictChip verdict={decision.verdict} />
          </span>
          <DirectionLabel direction={decision.direction} />
          <Address address={decision.counterparty} />
          <span className={styles.amount}>{formatAssetAmount(decision.amount, decision.asset)}</span>
        </div>
        <h3 className={styles.headline}>
          <Link className={styles.stretched} href={`/cases/${encodeURIComponent(decision.case_id)}`}>
            {decision.headline}
          </Link>
        </h3>
        {reasons.length ? (
          <ul className={styles.reasons} aria-label="Top reasons">
            {reasons.map((r) => (
              <li key={r.rule}>
                <ReasonText reason={r} clamp />
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.clear}>
            <Icon name="check" size={16} strokeWidth={2.6} />
            {decision.checks.length} checks ran; no policy rule triggered
          </p>
        )}
        <div className={styles.cardFoot}>
          <SourceTag source={detail?.source} />
          <span className={styles.footItem} title="Time from request to verdict">
            <Icon name="clock" size={15} />
            {formatMs(decision.latency_ms)}
          </span>
          <time className={styles.footItem} dateTime={decision.decided_at} title={decision.decided_at}>
            {formatClock(decision.decided_at)}
            {now ? ` · ${formatAgo(decision.decided_at, now)}` : ""}
          </time>
          <StatusChip status={decision.status} />
          <span className={styles.footSpacer} />
          <AttestationPill attestation={decision.attestation} />
        </div>
      </div>
    </article>
  );
}
