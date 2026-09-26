"use client";

import { useState } from "react";
import { Address, TxLink } from "@/components/ui/Address";
import { Button } from "@/components/ui/Button";
import { Icon, type IconName } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api";
import { awaitingDeposit, latestEvent, officerCanDecide } from "@/lib/cases";
import { describeError } from "@/lib/errors";
import { formatAssetAmount, shortAddress } from "@/lib/format";
import { useHealth, usePolicy } from "@/lib/hooks";
import type { CaseDetail, DecisionResponse, OfficerAction } from "@/lib/types";
import { STATUS_LABEL } from "@/lib/vocab";
import styles from "./case.module.css";

interface Progress {
  action: OfficerAction;
  phase: "sending" | "done" | "failed";
  response: DecisionResponse | null;
  error: unknown;
}

type RowState = "done" | "active" | "failed" | "waiting";

function ProgressRow({ state, children }: { state: RowState; children: React.ReactNode }) {
  const icon: IconName = state === "done" ? "allow" : state === "failed" ? "error" : state === "active" ? "spinner" : "clock";
  return (
    <li className={styles.progressRow} data-state={state}>
      <Icon name={icon} size={18} strokeWidth={2.4} className={state === "active" ? "spin" : undefined} />
      <span>{children}</span>
    </li>
  );
}

function ttlText(seconds: number | undefined): string {
  if (!seconds) return "1 hour";
  if (seconds % 86400 === 0) return seconds === 86400 ? "24 hours" : `${seconds / 86400} days`;
  if (seconds % 3600 === 0) return seconds === 3600 ? "1 hour" : `${seconds / 3600} hours`;
  return `${seconds} s`;
}

/** Officer actions for HOLD cases (PRD 9.11 decision endpoint, 6.4 review flow). */
export function OfficerActions({ c, onChanged }: { c: CaseDetail; onChanged: () => void }) {
  const { data: health } = useHealth();
  const { data: policy } = usePolicy();
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState<"release" | "refund" | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);

  const inbound = c.direction === "inbound";
  const decidable = officerCanDecide(c);
  const depositPending = awaitingDeposit(c);
  const resolved = c.status === "RELEASED" || c.status === "REFUNDED" || c.status === "CLEARED" || c.status === "REJECTED";
  const busy = progress?.phase === "sending";
  const amount = formatAssetAmount(c.amount, c.asset);
  const holdId = c.hold?.hold_id;
  const clearTtl = ttlText(policy?.parsed.officer_clear_ttl_seconds ?? 3600);
  const party = inbound ? "payer" : "payee";

  const run = async (action: OfficerAction) => {
    setConfirm(null);
    setProgress({ action, phase: "sending", response: null, error: null });
    try {
      const response = await api.decide(c.case_id, { action, note: note.trim() });
      setProgress({ action, phase: "done", response, error: null });
    } catch (error) {
      setProgress({ action, phase: "failed", response: null, error });
    } finally {
      onChanged();
    }
  };

  const overrideEvent = latestEvent(c.chain_events, "VerdictOverridden");
  const actionEvent = latestEvent(c.chain_events, progress?.action === "refund" ? "Refunded" : "Released");
  const overrideTx = progress?.response?.override_tx ?? c.hold?.override_tx ?? overrideEvent?.tx_hash ?? null;
  const actionTx = progress?.response?.action_tx ?? c.hold?.action_tx ?? actionEvent?.tx_hash ?? null;
  const failed = progress?.phase === "failed";
  const errorInfo = failed ? describeError(progress?.error) : null;
  const expectedRefusal = progress?.action === "release_unchecked" && errorInfo?.code === "NotCleared";

  const rows = (() => {
    if (!progress) return null;
    if (progress.action === "release_unchecked") {
      return (
        <ul className={styles.progress} aria-live="polite">
          <ProgressRow state="done">Decision sent to the gate (release without clearance)</ProgressRow>
          <ProgressRow state={progress.phase === "sending" ? "active" : failed ? (expectedRefusal ? "done" : "failed") : "done"}>
            <code>release(hold #{holdId})</code> with no officer override first
            {expectedRefusal ? ": refused by the escrow, as designed" : ""}
          </ProgressRow>
        </ul>
      );
    }
    const release = progress.action === "release";
    const finalStatus = inbound ? (release ? "CLEARED" : "REJECTED") : release ? "RELEASED" : "REFUNDED";
    const overrideState: RowState = overrideTx ? "done" : failed ? "failed" : "active";
    const actionState: RowState = actionTx ? "done" : failed && overrideTx ? "failed" : overrideTx ? "active" : "waiting";
    const statusDone = c.status === finalStatus || progress.response?.status === finalStatus;
    return (
      <ul className={styles.progress} aria-live="polite">
        <ProgressRow state="done">Decision sent to the gate, signed with the officer key</ProgressRow>
        <ProgressRow state={overrideState}>
          <code>overrideVerdict</code>: {release ? `clear the ${party} (ALLOW, ${clearTtl})` : `block the ${party} (BLOCK, one year)`}
          {overrideTx ? (
            <>
              {" "}
              · <TxLink hash={overrideTx} url={overrideEvent?.tx_hash === overrideTx ? overrideEvent.explorer_url : undefined} />
            </>
          ) : null}
        </ProgressRow>
        {!inbound ? (
          <ProgressRow state={actionState}>
            <code>
              {release ? "release" : "refund"}(hold #{holdId})
            </code>
            : {release ? "the escrow checks the registry, then pays the payee" : "the escrow returns the funds to the payer"}
            {actionTx ? (
              <>
                {" "}
                · <TxLink hash={actionTx} url={actionEvent?.tx_hash === actionTx ? actionEvent.explorer_url : undefined} />
              </>
            ) : null}
          </ProgressRow>
        ) : null}
        <ProgressRow state={statusDone ? "done" : failed ? "failed" : "waiting"}>
          Case status: {statusDone ? STATUS_LABEL[finalStatus] : `waiting for ${STATUS_LABEL[finalStatus].toLowerCase()}`}
        </ProgressRow>
      </ul>
    );
  })();

  const releaseLabel = inbound ? "Clear payer" : `Release to payee`;
  const refundLabel = inbound ? "Reject payer" : `Refund to payer`;
  const showForm = decidable && !busy && !(progress?.phase === "done" && progress.action !== "release_unchecked");

  return (
    <Panel
      id="officer"
      eyebrow="Human in the loop"
      title={resolved ? "Officer decision recorded" : "Officer decision"}
      footnote={
        !resolved ? "Signed server-side with the demo officer key; every write is composed through Curvegrid MultiBaas." : undefined
      }
    >
      <div className={styles.officer}>
        {depositPending ? (
          <p className={styles.muted} role="status">
            <Icon name="escrow" size={16} /> Signing is paused; no escrow deposit is confirmed. If the agent deposits, release and refund unlock when the Held event links the
            hold to this case.
          </p>
        ) : null}

        {resolved && !progress ? (
          <div className={styles.progress}>
            <span>
              <strong>{STATUS_LABEL[c.status]}</strong> by an officer
              {c.hold?.officer_note ? <>: “{c.hold.officer_note}”</> : "."}
            </span>
            {overrideTx ? (
              <span className={styles.muted}>
                Override tx <TxLink hash={overrideTx} />
              </span>
            ) : null}
            {c.hold?.action_tx ? (
              <span className={styles.muted}>
                {c.status === "REFUNDED" ? "Refund" : "Release"} tx <TxLink hash={c.hold.action_tx} />
              </span>
            ) : null}
          </div>
        ) : null}

        {rows}

        {errorInfo ? (
          <div className={styles.revert} data-expected={expectedRefusal || undefined} role="alert">
            <span className={styles.revertTitle}>
              <Icon name={expectedRefusal ? "shield" : "error"} size={18} />
              {expectedRefusal ? "The escrow refused, as designed: NotCleared" : errorInfo.title}
            </span>
            {errorInfo.explain ? <span>{errorInfo.explain}</span> : null}
            <span className={styles.muted}>{errorInfo.message}</span>
            <span className={styles.revertCode}>
              {progress?.error && typeof progress.error === "object" && "status" in progress.error
                ? `HTTP ${(progress.error as { status: number }).status} · `
                : ""}
              error: {errorInfo.code}
            </span>
          </div>
        ) : null}

        {showForm ? (
          <>
            <label className={styles.noteField}>
              <span className={styles.noteLabel}>Review note</span>
              <span className={styles.noteHint}>Its keccak256 hash is recorded onchain with your decision.</span>
              <textarea
                className={`${styles.textarea} resize-none`}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={
                  inbound ? "Why are you clearing or rejecting this payer?" : "Why are you releasing or refunding this payment?"
                }
                maxLength={4000}
              />
            </label>
            <div className={styles.actionRow}>
              <Button variant="primary" onClick={() => setConfirm("release")}>
                <Icon name="allow" size={18} strokeWidth={2.4} />
                {releaseLabel}
              </Button>
              <Button variant="danger" onClick={() => setConfirm("refund")}>
                <Icon name={inbound ? "block" : "arrowLeft"} size={18} strokeWidth={2.4} />
                {refundLabel}
              </Button>
            </div>
            {health?.demo_mode && !inbound ? (
              <div className={styles.demoOnly}>
                <span className={styles.demoOnlyTitle}>
                  <Icon name="alert" size={15} />
                  Demo only
                </span>
                <span className={styles.muted}>
                  Calls <code>release(hold #{holdId})</code> without recording an officer override first. The escrow contract should
                  refuse with NotCleared.
                </span>
                <div>
                  <Button small onClick={() => void run("release_unchecked")}>
                    Release without clearance
                  </Button>
                </div>
              </div>
            ) : null}
          </>
        ) : null}
      </div>

      <Modal
        open={confirm !== null}
        title={
          confirm === "release"
            ? inbound
              ? `Clear payer ${shortAddress(c.counterparty)}?`
              : `Release ${amount} to ${shortAddress(c.counterparty)}?`
            : inbound
              ? `Reject payer ${shortAddress(c.counterparty)}?`
              : `Refund ${amount} to the paying agent?`
        }
        onClose={() => setConfirm(null)}
      >
        <p>
          {inbound ? "One transaction" : "Two transactions"} from the officer key, composed through Curvegrid MultiBaas:
        </p>
        <ol className={styles.modalList}>
          {confirm === "release" ? (
            <li>
              <code>overrideVerdict</code>: clear the {party} (ALLOW) for {clearTtl} in the ComplianceRegistry
              {inbound ? ". Their next payment attempt passes." : "."}
            </li>
          ) : (
            <li>
              <code>overrideVerdict</code>: block the {party} (BLOCK) for one year in the ComplianceRegistry.
            </li>
          )}
          {!inbound ? (
            <li>
              <code>
                {confirm === "release" ? "release" : "refund"}(hold #{holdId})
              </code>
              :{" "}
              {confirm === "release"
                ? "the ComplianceEscrow checks the registry, then pays the payee."
                : "the ComplianceEscrow returns the funds to the paying agent."}
            </li>
          ) : null}
        </ol>
        <p style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          Counterparty <Address address={c.counterparty} />
        </p>
        {confirm === "refund" ? (
          <div className={styles.modalWarning}>
            <Icon name="alert" size={18} />
            <span>
              This blocks {shortAddress(c.counterparty)} for one year: future payments {inbound ? "from" : "to"} it are refused by rule 0.
            </span>
          </div>
        ) : null}
        <p className={styles.muted}>{note.trim() ? <>Your note: “{note.trim()}”</> : "No note. The hash of an empty note is recorded."}</p>
        <div className={styles.modalActions}>
          <Button onClick={() => setConfirm(null)}>Cancel</Button>
          <Button variant={confirm === "refund" ? "danger" : "primary"} onClick={() => confirm && void run(confirm)} autoFocus>
            {confirm === "release" ? (inbound ? "Clear payer" : `Release ${amount}`) : inbound ? "Reject payer" : `Refund ${amount}`}
          </Button>
        </div>
      </Modal>
    </Panel>
  );
}
