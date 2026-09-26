"use client";

import Link from "next/link";
import { useEffect } from "react";
import { Icon } from "@/components/ui/Icon";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/Panel";
import { GateError } from "@/lib/errors";
import { useCaseDetail } from "@/lib/hooks";
import { AnalystNote } from "./AnalystNote";
import { CaseHeader } from "./CaseHeader";
import { DecisionTimeline } from "./DecisionTimeline";
import { EvidencePanel } from "./EvidencePanel";
import { OfficerActions } from "./OfficerActions";
import { OnchainProof } from "./OnchainProof";
import { SourceOfFunds } from "./SourceOfFunds";
import { UntrustedContext } from "./UntrustedContext";
import styles from "./case.module.css";

export function CaseView({ caseId }: { caseId: string }) {
  const { data: c, error, mutate } = useCaseDetail(caseId);
  const loaded = Boolean(c);

  // Deep links such as /cases/{id}#proof: scroll once the panels exist.
  useEffect(() => {
    if (!loaded) return;
    const hash = window.location.hash.slice(1);
    if (hash) document.getElementById(hash)?.scrollIntoView({ block: "start" });
  }, [loaded]);

  const back = (
    <Link href="/" className={styles.back}>
      <Icon name="arrowLeft" size={18} />
      Live decisions
    </Link>
  );

  if (!c) {
    const notFound = error instanceof GateError && error.status === 404;
    return (
      <div className={styles.page}>
        {back}
        {notFound ? (
          <EmptyState title="Case not found">
            No case <code>{caseId}</code> on this gate. Check the link, or open one from the live feed.
          </EmptyState>
        ) : error ? (
          <ErrorState error={error} onRetry={() => void mutate()} />
        ) : (
          <LoadingState label="Loading the case" />
        )}
      </div>
    );
  }

  return (
    <div className={styles.page}>
      {back}
      <CaseHeader c={c} stamp />
      {error ? <ErrorState error={error} onRetry={() => void mutate()} /> : null}
      {c.untrusted_context ? <UntrustedContext text={c.untrusted_context} /> : null}
      <div className={styles.columns}>
        <div className={styles.column}>
          <div className={styles.orderTimeline}>
            <DecisionTimeline c={c} />
          </div>
        </div>
        <div className={styles.column}>
          {c.verdict === "HOLD" ? (
            <div className={styles.orderOfficer}>
              <OfficerActions c={c} onChanged={() => void mutate()} />
            </div>
          ) : null}
          <div className={styles.orderAnalyst}>
            <AnalystNote c={c} />
          </div>
          <div className={styles.orderProof}>
            <OnchainProof c={c} />
          </div>
        </div>
      </div>
      <EvidencePanel c={c} />
      <SourceOfFunds c={c} />
    </div>
  );
}
