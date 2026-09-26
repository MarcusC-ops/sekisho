import type { ReactNode } from "react";
import { TxLink } from "@/components/ui/Address";
import { Icon, type IconName } from "@/components/ui/Icon";
import { Panel } from "@/components/ui/Panel";
import { LiveTag, Tag } from "@/components/ui/Pills";
import { ReasonText, sortReasons } from "@/components/ui/Reason";
import { VerdictIcon, verdictTone } from "@/components/ui/Verdict";
import { latestEvent } from "@/lib/cases";
import { formatAssetAmount, formatClock, formatMs } from "@/lib/format";
import type { CaseDetail, Check } from "@/lib/types";
import { checkTitle } from "@/lib/vocab";
import styles from "./timeline.module.css";

type StepState = "ok" | "error" | "skipped" | "pending" | "done" | "refused";
type Line = "solid" | "tone" | "dashed" | "dotted" | "none";

function Step({
  icon,
  state,
  tone,
  line = "solid",
  title,
  tags,
  right,
  children,
  bar,
  spin = false,
}: {
  icon: IconName | ReactNode;
  state: StepState;
  tone?: "allow" | "hold" | "block" | "neutral" | "accent";
  line?: Line;
  title: ReactNode;
  tags?: ReactNode;
  right?: ReactNode;
  children?: ReactNode;
  bar?: number | null;
  spin?: boolean;
}) {
  return (
    <li className={styles.step} data-state={state} data-tone={tone} data-line={line}>
      <span className={styles.node} aria-hidden="true">
        {typeof icon === "string" ? (
          <Icon name={icon as IconName} size={19} strokeWidth={2.4} className={spin ? "spin" : undefined} />
        ) : (
          icon
        )}
      </span>
      <div className={styles.body}>
        <div className={styles.head}>
          <span className={styles.title}>{title}</span>
          {tags ? <span className={styles.tags}>{tags}</span> : null}
          {right}
        </div>
        {children ? <div className={styles.detail}>{children}</div> : null}
        {bar !== undefined && bar !== null ? (
          <div className={styles.waterfall} aria-hidden="true">
            <div className={styles.waterfallFill} style={{ width: `${Math.max(1.5, Math.min(100, bar * 100))}%` }} />
          </div>
        ) : null}
      </div>
    </li>
  );
}

function requestStep(c: CaseDetail): { title: string; detail: ReactNode } {
  const amount = formatAssetAmount(c.amount, c.asset);
  const purpose = c.purpose ? <> · purpose: {c.purpose}</> : null;
  if (c.source === "x402" && c.direction === "outbound") {
    return {
      title: "Payment request received (402)",
      detail: (
        <>
          <strong>{c.agent_id}</strong> was asked for <strong>{amount}</strong>
          {c.resource ? <> by {c.resource}</> : null}
          {purpose}
        </>
      ),
    };
  }
  if (c.source === "x402") {
    return {
      title: "Payment received for verification (x402)",
      detail: (
        <>
          <strong>{c.agent_id}</strong> was offered <strong>{amount}</strong> by this payer; screening runs before verification.
        </>
      ),
    };
  }
  if (c.source === "direct") {
    return {
      title: c.direction === "outbound" ? "Direct transfer requested (pay_invoice)" : "Direct transfer received",
      detail: (
        <>
          <strong>{c.agent_id}</strong> asked to send <strong>{amount}</strong>
          {purpose}
        </>
      ),
    };
  }
  return {
    title: "Screening requested over MCP",
    detail: (
      <>
        <strong>{c.agent_id || "An MCP agent"}</strong> asked to screen a {c.direction === "outbound" ? "payee" : "payer"} for{" "}
        <strong>{amount}</strong>
        {purpose}
      </>
    ),
  };
}

function checkStep(check: Check, scale: number) {
  const state: StepState = check.status === "ok" ? "ok" : check.status === "error" ? "error" : "skipped";
  return (
    <Step
      key={check.name}
      icon={state === "ok" ? "check" : state === "error" ? "error" : "skip"}
      state={state}
      title={checkTitle(check.name)}
      tags={<LiveTag live={check.live} />}
      right={<span className={styles.ms}>{formatMs(check.latency_ms)}</span>}
      bar={check.latency_ms !== null && scale > 0 ? check.latency_ms / scale : null}
    >
      {check.status === "error" ? (
        <span className={styles.errorText}>Failed: {check.error ?? check.summary}</span>
      ) : check.status === "skipped" ? (
        <>Skipped{check.summary ? `: ${check.summary}` : ""}</>
      ) : (
        check.summary
      )}
      {check.evidence_id ? <> · evidence {check.evidence_id}</> : null}
    </Step>
  );
}

/** Steps after the policy gate, derived from the case state and its chain events. */
function outcomeSteps(c: CaseDetail): ReactNode[] {
  const steps: ReactNode[] = [];
  const overrideEvent = latestEvent(c.chain_events, "VerdictOverridden");
  const releasedEvent = latestEvent(c.chain_events, "Released");
  const refundedEvent = latestEvent(c.chain_events, "Refunded");
  const tone = verdictTone(c.verdict);

  if (c.verdict === "BLOCK") {
    steps.push(
      <Step key="refused" icon="block" state="refused" tone="block" line="dotted" title={c.direction === "outbound" ? "No signature produced" : "Refused before verification"}>
        {c.direction === "outbound"
          ? "The agent was refused before it signed anything, so there is no payment to claw back."
          : "The vendor refused the payer's authorisation before verification or settlement. Nothing moved."}
      </Step>,
    );
    return steps;
  }

  if (c.verdict === "ALLOW") {
    if (c.direction === "inbound") {
      steps.push(
        <Step key="accepted" icon="check" state="done" tone="allow" line="dotted" title="Payer accepted">
          The vendor went on to verify and settle the payment.
        </Step>,
      );
    } else if (c.payment_tx || c.status === "PAID") {
      steps.push(
        <Step
          key="settled"
          icon="check"
          state="done"
          tone="allow"
          line="dotted"
          title={
            <>
              Signed and settled, tx <TxLink hash={c.payment_tx} />
            </>
          }
        >
          The agent signed the EIP-3009 authorisation and x402 settled it on Base Sepolia.
        </Step>,
      );
    } else {
      steps.push(
        <Step key="settling" icon="clock" state="pending" line="dotted" title="Cleared to sign; waiting for the settlement report">
          The agent reports the x402 settlement tx when it lands.
        </Step>,
      );
    }
    return steps;
  }

  // HOLD
  if (c.direction === "inbound") {
    steps.push(
      <Step key="held" icon="hold" state="done" tone="hold" line={c.status === "DECIDED" ? "dashed" : "tone"} title="Payer refused for now, held for review">
        A seller can&apos;t escrow a payer&apos;s funds. An officer can clear or reject this payer.
      </Step>,
    );
    if (c.status === "CLEARED" || c.status === "REJECTED") {
      const cleared = c.status === "CLEARED";
      steps.push(
        <Step
          key="officer"
          icon="officer"
          state="done"
          tone={cleared ? "allow" : "block"}
          line="dotted"
          title={
            <>
              {cleared ? "Payer cleared by officer" : "Payer rejected by officer"}
              {overrideEvent ? (
                <>
                  , tx <TxLink hash={overrideEvent.tx_hash} url={overrideEvent.explorer_url} />
                </>
              ) : null}
            </>
          }
        >
          {cleared
            ? "The payer's next attempt passes through the officer override (rule 0)."
            : "The payer is blocked in the ComplianceRegistry."}
        </Step>,
      );
    } else {
      steps.push(
        <Step key="waiting" icon="officer" state="pending" line="dotted" title="Waiting for a compliance officer">
          Clear or reject the payer from the officer panel.
        </Step>,
      );
    }
    return steps;
  }

  if (!c.hold) {
    steps.push(
      <Step key="deposit" icon="escrow" state="pending" tone={tone} line="dotted" title="Payment aborted before signing; waiting for the escrow deposit">
        The agent deposits the amount into ComplianceEscrow; the Held event links it here.
      </Step>,
    );
    return steps;
  }

  const overrideTx = c.hold.override_tx ?? overrideEvent?.tx_hash ?? null;
  const released = c.status === "RELEASED" || c.hold.status === "RELEASED";
  const refunded = c.status === "REFUNDED" || c.hold.status === "REFUNDED";
  steps.push(
    <Step
      key="escrow"
      icon="escrow"
      state="done"
      tone="hold"
      line={released || refunded || overrideTx ? "tone" : "dashed"}
      title={<>Held in escrow, hold #{c.hold.hold_id}</>}
    >
      Deposit tx <TxLink hash={c.hold.deposit_tx} />. ComplianceEscrow releases only to a payee the registry shows as cleared.
    </Step>,
  );
  if (overrideTx) {
    const clearedByOfficer = released || (!refunded && overrideEvent && Number((overrideEvent.inputs as { next?: unknown }).next) === 1);
    steps.push(
      <Step
        key="override"
        icon="officer"
        state="done"
        tone={clearedByOfficer ? "allow" : "block"}
        line="tone"
        title={
          <>
            {clearedByOfficer ? "Officer cleared the counterparty" : "Officer blocked the counterparty"}, tx{" "}
            <TxLink hash={overrideTx} url={overrideEvent?.tx_hash === overrideTx ? overrideEvent?.explorer_url : undefined} />
          </>
        }
      >
        {c.hold.officer_note ? <>Note: “{c.hold.officer_note}”</> : "overrideVerdict in the ComplianceRegistry."}
      </Step>,
    );
  }
  if (released) {
    const tx = c.hold.action_tx ?? releasedEvent?.tx_hash ?? null;
    steps.push(
      <Step key="released" icon="check" state="done" tone="allow" line="dotted" title={<>Released to payee, tx <TxLink hash={tx} /></>}>
        The escrow checked the registry, found the payee cleared and paid out.
      </Step>,
    );
  } else if (refunded) {
    const tx = c.hold.action_tx ?? refundedEvent?.tx_hash ?? null;
    steps.push(
      <Step key="refunded" icon="arrowLeft" state="done" tone="neutral" line="dotted" title={<>Refunded to payer, tx <TxLink hash={tx} /></>}>
        The held amount went back to the paying agent.
      </Step>,
    );
  } else {
    steps.push(
      <Step key="waiting" icon="officer" state="pending" line="dotted" title={overrideTx ? "Officer decision in progress" : "Waiting for a compliance officer"}>
        {overrideTx ? "The escrow transaction follows the override." : "Release or refund from the officer panel."}
      </Step>,
    );
  }
  return steps;
}

function attestationStep(c: CaseDetail) {
  const { status, tx_hash, explorer_url, error } = c.attestation;
  const screened = latestEvent(c.chain_events, "Screened");
  if (status === "confirmed") {
    return (
      <Step
        key="attest"
        icon="chain"
        state="done"
        tone="accent"
        title={
          <>
            Attestation confirmed, tx <TxLink hash={tx_hash} url={explorer_url} />
          </>
        }
        right={screened?.block_number ? <span className={styles.meta}>block {screened.block_number.toLocaleString("en-US")}</span> : null}
      >
        recordScreening through Curvegrid MultiBaas: verdict, risk score, report hash and policy id are onchain.
      </Step>
    );
  }
  if (status === "failed") {
    return (
      <Step key="attest" icon="error" state="error" title="Attestation failed">
        <span className={styles.errorText}>{error ?? "The recordScreening transaction failed."}</span>
      </Step>
    );
  }
  return (
    <Step
      key="attest"
      icon={status === "submitted" ? "spinner" : "clock"}
      spin={status === "submitted"}
      state="pending"
      title={
        status === "submitted" ? (
          <>
            Attestation submitted, tx <TxLink hash={tx_hash} url={explorer_url} />
          </>
        ) : (
          "Attestation queued"
        )
      }
    >
      recordScreening through Curvegrid MultiBaas, in the background: the verdict never waits for the chain.
    </Step>
  );
}

export function DecisionTimeline({ c }: { c: CaseDetail }) {
  const decisionChecks = c.checks.filter((k) => k.name !== "intercepta.deep_scan");
  const deepScan = c.checks.find((k) => k.name === "intercepta.deep_scan");
  const scale = Math.max(c.latency_ms, ...decisionChecks.map((k) => k.latency_ms ?? 0));
  const request = requestStep(c);
  const tone = verdictTone(c.verdict);
  const reasons = sortReasons(c.reasons);
  const rules = c.policy.triggered_rules.filter((r) => r !== "default");
  const startedAt = new Date(Date.parse(c.decided_at) - c.latency_ms).toISOString();
  const afterGate: Line = c.verdict === "HOLD" ? "dashed" : "tone";

  return (
    <Panel
      id="timeline"
      eyebrow="The moment of decision"
      title="Decision timeline"
      actions={
        <span className={styles.meta} style={{ marginLeft: 0 }}>
          {decisionChecks.length} checks · verdict in {formatMs(c.latency_ms)}
        </span>
      }
    >
      <ol className={styles.timeline}>
        <Step icon="arrowRight" state="ok" title={request.title} right={<span className={styles.meta}>{formatClock(startedAt)}</span>}>
          {request.detail}
        </Step>

        <li className={styles.group} aria-hidden="true">
          <span />
          <div className={styles.groupHead}>
            <span>Checks run in parallel, before anything is signed</span>
            <span className={styles.scale}>0 → {formatMs(scale)}</span>
          </div>
        </li>
        {decisionChecks.map((check) => checkStep(check, scale))}

        <li className={styles.gate} data-tone={tone} data-line={afterGate === "dashed" ? "dashed" : undefined}>
          <span className={styles.gateNode} aria-hidden="true">
            <VerdictIcon verdict={c.verdict} size={21} />
          </span>
          <div className={styles.body}>
            <div className={styles.head}>
              <span className={styles.gateTitle}>
                Policy v{c.policy.version}: <span className={styles.gateVerdict}>{c.verdict}</span>{" "}
                {rules.length ? `(${rules.length} ${rules.length === 1 ? "rule" : "rules"})` : "(no rule triggered)"}
              </span>
              <span className={styles.ms}>{formatMs(c.latency_ms)}</span>
            </div>
            {reasons.length ? (
              <ul className={styles.gateReasons}>
                {reasons.map((r) => (
                  <li key={r.rule}>
                    <ReasonText reason={r} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.detail}>Every check ran and nothing in the policy matched, so the payment may proceed.</p>
            )}
            {rules.length ? (
              <div className={styles.rules} aria-label="Triggered rules">
                {rules.map((r) => (
                  <code key={r} className={styles.rule}>
                    {r}
                  </code>
                ))}
              </div>
            ) : null}
          </div>
        </li>

        {outcomeSteps(c)}

        {deepScan ? (
          <Step
            icon={deepScan.status === "ok" ? "check" : "error"}
            state={deepScan.status === "ok" ? "ok" : "error"}
            line="dotted"
            title="Intercepta Deep Scan"
            tags={
              <>
                <LiveTag live={deepScan.live} />
                <Tag>After HOLD</Tag>
              </>
            }
            right={<span className={styles.ms}>{formatMs(deepScan.latency_ms)}</span>}
          >
            {deepScan.status === "ok" ? deepScan.summary : deepScan.error}. Enrichment for the officer; it did not change the verdict.
          </Step>
        ) : null}

        {attestationStep(c)}
      </ol>
    </Panel>
  );
}
