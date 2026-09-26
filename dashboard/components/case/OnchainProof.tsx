"use client";

import Link from "next/link";
import { useState } from "react";
import { HashValue, TxLink } from "@/components/ui/Address";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Panel } from "@/components/ui/Panel";
import { AttestationPill } from "@/components/ui/Pills";
import { api } from "@/lib/api";
import { latestEvent } from "@/lib/cases";
import { describeError } from "@/lib/errors";
import { formatInt, shortHash } from "@/lib/format";
import type { CaseDetail } from "@/lib/types";
import { verifyReport, type VerifyOutcome } from "@/lib/verify";
import styles from "./case.module.css";

function CompareRow({ ok, children }: { ok: boolean | null; children: React.ReactNode }) {
  return (
    <div className={styles.compareRow} data-ok={ok === null ? "pending" : String(ok)}>
      <Icon name={ok === null ? "clock" : ok ? "allow" : "block"} size={18} strokeWidth={2.4} />
      <div>{children}</div>
    </div>
  );
}

function VerifyResult({ outcome }: { outcome: VerifyOutcome }) {
  const tone = outcome.result === "match" ? "allow" : outcome.result === "mismatch" ? "block" : "hold";
  const title =
    outcome.result === "match" ? "Match" : outcome.result === "mismatch" ? "Mismatch" : "Match with the gate; onchain event not indexed yet";
  return (
    <div className={styles.verify} data-tone={tone} role="status" aria-live="polite">
      <span className={styles.verifyResult}>
        <Icon name={outcome.result === "match" ? "allow" : outcome.result === "mismatch" ? "block" : "clock"} size={26} strokeWidth={2.4} />
        {title}
      </span>
      <div className={styles.compare}>
        <CompareRow ok={true}>
          Fetched <code>GET /v1/reports/{shortHash(outcome.caseHash)}</code> as text: {formatInt(outcome.chars)} characters,{" "}
          {formatInt(outcome.bytes)} bytes (UTF-8). Hashed in this browser with viem <code>keccak256(stringToBytes(text))</code>:
          <span className={styles.hashLine}>{outcome.computed}</span>
        </CompareRow>
        <CompareRow ok={outcome.matchesCase}>
          {outcome.matchesCase ? "Equals" : "Does not equal"} the case&apos;s <code>report_hash</code>:
          <span className={styles.hashLine}>{outcome.caseHash}</span>
        </CompareRow>
        <CompareRow ok={outcome.matchesOnchain}>
          {outcome.onchain ? (
            <>
              {outcome.matchesOnchain ? "Equals" : "Does not equal"} the onchain <code>Screened.reportHash</code>
              {outcome.onchain.block ? ` (block ${outcome.onchain.block.toLocaleString("en-US")}` : " ("}
              {outcome.onchain.txHash ? (
                <>
                  , tx <TxLink hash={outcome.onchain.txHash} url={outcome.onchain.explorerUrl} />
                </>
              ) : null}
              ), read from {outcome.onchain.via === "audit" ? "the audit log (/v1/audit)" : "the case's chain events"}, indexed by
              Curvegrid MultiBaas:
              <span className={styles.hashLine}>{outcome.onchain.reportHash}</span>
            </>
          ) : (
            "No Screened event for this case has been indexed yet, so there is no onchain hash to compare. Try again once the attestation confirms."
          )}
        </CompareRow>
      </div>
      {outcome.result === "mismatch" ? (
        <p className={styles.muted}>
          The served bytes differ from what was attested: the evidence changed after the decision, or this is the wrong report.
        </p>
      ) : null}
    </div>
  );
}

export function OnchainProof({ c }: { c: CaseDetail }) {
  const [verifying, setVerifying] = useState(false);
  const [outcome, setOutcome] = useState<VerifyOutcome | null>(null);
  const [verifyError, setVerifyError] = useState<unknown>(null);
  const [rawOpen, setRawOpen] = useState(false);
  const [rawText, setRawText] = useState<string | null>(null);
  const [rawError, setRawError] = useState<unknown>(null);
  const [pretty, setPretty] = useState(false);
  const screened = latestEvent(c.chain_events, "Screened");

  const verify = async () => {
    setVerifying(true);
    setVerifyError(null);
    try {
      const result = await verifyReport(c);
      setOutcome(result);
      setRawText(result.text);
    } catch (error) {
      setOutcome(null);
      setVerifyError(error);
    } finally {
      setVerifying(false);
    }
  };

  const toggleRaw = async () => {
    const next = !rawOpen;
    setRawOpen(next);
    if (next && rawText === null) {
      try {
        setRawText(await api.reportText(c.report_hash));
      } catch (error) {
        setRawError(error);
      }
    }
  };

  let prettyText: string | null = null;
  if (pretty && rawText) {
    try {
      prettyText = JSON.stringify(JSON.parse(rawText), null, 2);
    } catch {
      prettyText = rawText;
    }
  }

  return (
    <Panel id="proof" eyebrow="Tamper-evident record" title="Onchain proof">
      <dl className={styles.facts}>
        <dt>Report hash</dt>
        <dd>
          <HashValue value={c.report_hash} label="report hash" />
        </dd>
        <dt>Policy</dt>
        <dd>
          <Link href="/policy">v{c.policy.version}</Link> <HashValue value={c.policy.id} label="policy id" />
        </dd>
        <dt>Case id (bytes32)</dt>
        <dd>
          <HashValue value={c.case_id_b32} label="case id bytes32" />
        </dd>
        <dt>Attestation</dt>
        <dd style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <AttestationPill attestation={c.attestation} />
          {screened?.block_number ? <span className={styles.muted}>block {screened.block_number.toLocaleString("en-US")}</span> : null}
        </dd>
      </dl>

      <div className={styles.proofActions}>
        <Button variant="primary" onClick={() => void verify()} disabled={verifying}>
          <Icon name={verifying ? "spinner" : "shield"} size={18} className={verifying ? "spin" : undefined} />
          {verifying ? "Verifying" : outcome ? "Verify again" : "Verify report"}
        </Button>
        <Button onClick={() => void toggleRaw()} aria-expanded={rawOpen}>
          <Icon name="code" size={18} />
          {rawOpen ? "Hide report JSON" : "Show report JSON"}
        </Button>
      </div>

      {verifyError ? (
        <div className={styles.revert} role="alert" style={{ marginTop: 16 }}>
          <span className={styles.revertTitle}>
            <Icon name="error" size={18} />
            Couldn&apos;t verify: {describeError(verifyError).title}
          </span>
          <span>{describeError(verifyError).message}</span>
        </div>
      ) : null}
      {outcome ? <VerifyResult outcome={outcome} /> : null}

      {rawOpen ? (
        rawError ? (
          <p className={styles.muted} role="alert">
            Report unavailable: {describeError(rawError).message}
          </p>
        ) : rawText === null ? (
          <p className={styles.muted}>Loading the report…</p>
        ) : (
          <>
            <div className={styles.rawBar}>
              <span>
                {pretty
                  ? "Formatted for reading. Verify hashes the exact served text, not this view."
                  : "The exact canonical text the gate served (sorted keys, no spaces, UTF-8)."}
              </span>
              <Button small variant="ghost" onClick={() => setPretty(!pretty)}>
                {pretty ? "Show exact text" : "Pretty-print"}
              </Button>
            </div>
            <pre className={styles.raw}>{pretty ? prettyText : rawText}</pre>
          </>
        )
      ) : null}
    </Panel>
  );
}
