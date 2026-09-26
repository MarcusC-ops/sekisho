import { Icon } from "@/components/ui/Icon";
import { LoadingState, Panel } from "@/components/ui/Panel";
import { Tag } from "@/components/ui/Pills";
import { formatDateTime } from "@/lib/format";
import type { CaseDetail } from "@/lib/types";
import { EVIDENCE_ANCHOR } from "@/lib/vocab";
import styles from "./case.module.css";

function recommendationLabel(rec: string, inbound: boolean): string {
  if (rec === "release") return inbound ? "Clear the payer (release)" : "Release to the payee";
  if (rec === "refund") return inbound ? "Reject the payer (refund)" : "Refund the payer";
  return "No officer action";
}

/** The AI analyst's case note. Advisory only: the deterministic policy decides. */
export function AnalystNote({ c }: { c: CaseDetail }) {
  const note = c.analyst;
  const eyebrow = (
    <span className={styles.advisory}>
      <Icon name="note" size={15} />
      AI analyst · Advisory, does not decide
    </span>
  );

  if (!note) {
    return (
      <Panel id="analyst" eyebrow={eyebrow} title="Analyst note">
        <LoadingState label="The analyst is writing the case note" />
        <p className={styles.muted} style={{ textAlign: "center" }}>
          It arrives a few seconds after the decision. The verdict never waits for it.
        </p>
      </Panel>
    );
  }

  const disagrees = !note.agrees_with_policy;
  return (
    <Panel
      id="analyst"
      eyebrow={eyebrow}
      title={note.headline}
      actions={
        disagrees || note.fallback ? (
          <span className={styles.flagRow}>
            {disagrees ? (
              <span className={styles.flagChip} title="The analyst's reading differs from the policy. The verdict stands: the policy decides.">
                <Icon name="flag" size={16} />
                Analyst disagrees
              </span>
            ) : null}
            {note.fallback ? <Tag title="Built from the triggered rules; no language model was used">Template note</Tag> : null}
          </span>
        ) : null
      }
    >
      <div className={styles.analyst}>
        <p className={styles.analystSummary}>{note.summary}</p>
        {note.key_findings.length ? (
          <ul className={styles.findings} aria-label="Key findings">
            {note.key_findings.map((finding, i) => (
              <li key={i} className={styles.finding}>
                <Icon name="chevronDown" size={16} style={{ transform: "rotate(-90deg)" }} />
                <span>
                  {finding.text}
                  {finding.evidence.map((id) => {
                    const target = EVIDENCE_ANCHOR[id];
                    return target ? (
                      <a key={id} className={styles.evidenceChip} href={`#${target.anchor}`} title={`Evidence ${id}: ${target.label}`}>
                        {id}
                      </a>
                    ) : (
                      <span key={id} className={styles.evidenceChip}>
                        {id}
                      </span>
                    );
                  })}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        {c.verdict === "HOLD" ? (
          <div className={styles.recommendation}>
            <span className={styles.recommendationTitle}>
              Recommends: {recommendationLabel(note.officer_recommendation, c.direction === "inbound")}
            </span>
            <span className={styles.muted}>{note.recommendation_rationale}</span>
          </div>
        ) : note.recommendation_rationale ? (
          <p className={styles.muted}>{note.recommendation_rationale}</p>
        ) : null}
        <p className={styles.ownerMessage}>
          <strong>To the agent&apos;s owner:</strong> {note.owner_message}
        </p>
        <p className={styles.provenance}>
          {note.provider === "template" ? "Template note (no model)" : `${note.provider} · ${note.model ?? "model unknown"}`} ·{" "}
          {formatDateTime(note.generated_at)}. Not part of the hashed report.
        </p>
      </div>
    </Panel>
  );
}
