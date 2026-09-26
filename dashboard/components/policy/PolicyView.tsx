"use client";

import { PageHeader } from "@/components/shell/PageHeader";
import { HashValue } from "@/components/ui/Address";
import { DataState, Panel } from "@/components/ui/Panel";
import { usePolicy } from "@/lib/hooks";
import { formatUsd } from "@/lib/format";
import styles from "@/components/ui/data.module.css";

export function PolicyView() {
  const query = usePolicy();
  return <div className={styles.stack}>
    <PageHeader title="Demo policy" lede="The policy decides; the AI explains. This read-only policy is a hackathon demonstration, not a certified AML programme or legal advice." />
    <DataState {...query} onRetry={() => void query.mutate()} loadingLabel="Loading policy">
      {(policy) => <>
        <Panel id="policy-version" title={`${policy.name} · v${policy.version}`}>
          <div className={styles.prose}><p>The policy ID hashes the exact YAML bytes. Changing even whitespace creates a new ID.</p><HashValue value={policy.id} label="policy ID" /></div>
        </Panel>
        <Panel id="policy-thresholds" title="Decision thresholds">
          <div className={styles.prose}>
            <p>Direct sanctions hits and hard-block traits produce BLOCK. A failed required screen produces at least HOLD.</p>
            {policy.parsed.thresholds ? <ul className={styles.prose}>
              <li>Intercepta score: HOLD at {policy.parsed.thresholds.hold_score ?? "—"}; BLOCK at {policy.parsed.thresholds.block_score ?? "—"}.</li>
              <li>Flagged source-of-funds share: HOLD at {policy.parsed.thresholds.taint_hold_pct ?? "—"}%; BLOCK at {policy.parsed.thresholds.taint_block_pct ?? "—"}%.</li>
              <li>First payment to a new counterparty: HOLD above {formatUsd(policy.parsed.thresholds.first_time_max_usd)}.</li>
            </ul> : null}
            <p>These thresholds are only part of the policy. Trait rules, screening errors, and officer overrides also affect the result; the complete rules are below.</p>
          </div>
        </Panel>
        <Panel id="policy-yaml" title="Exact policy YAML"><pre className={styles.code} tabIndex={0} aria-label="Read-only policy YAML">{policy.yaml}</pre></Panel>
      </>}
    </DataState>
  </div>;
}
