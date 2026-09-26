import { REASON_SOURCE_LABEL } from "@/lib/vocab";
import type { Reason } from "@/lib/types";
import { Icon } from "./Icon";
import styles from "./reason.module.css";

export function isTraitReason(reason: Reason): boolean {
  return reason.rule.startsWith("hard_block_trait:") || reason.rule.startsWith("hold_trait:");
}

/** Block reasons first, otherwise in the policy's evaluation order. */
export function sortReasons(reasons: Reason[]): Reason[] {
  return reasons
    .map((reason, index) => ({ reason, index }))
    .sort((a, b) => (a.reason.severity === b.reason.severity ? a.index - b.index : a.reason.severity === "block" ? -1 : 1))
    .map((x) => x.reason);
}

/**
 * One triggered rule. Intercepta trait reasons show the trait name and Intercepta's own
 * description verbatim (in quotes, never paraphrased).
 */
export function ReasonText({ reason, clamp = false }: { reason: Reason; clamp?: boolean }) {
  const trait = isTraitReason(reason);
  return (
    <span className={`${styles.reason} ${clamp ? styles.clamp : ""}`}>
      <span className={styles.icon} data-tone={reason.severity === "block" ? "block" : "hold"}>
        <Icon name={reason.severity === "block" ? "block" : "hold"} size={17} strokeWidth={2.4} label={reason.severity === "block" ? "Block rule" : "Hold rule"} />
      </span>
      <span className={styles.text}>
        <span className={styles.source}>{REASON_SOURCE_LABEL[reason.source] ?? reason.source}</span>{" "}
        <strong className={trait ? styles.trait : styles.label}>{reason.label}</strong>{" "}
        {trait ? (
          <q className={styles.verbatim} title="Intercepta's description, verbatim">
            {reason.detail}
          </q>
        ) : (
          <span className={styles.detail}>{reason.detail}</span>
        )}
      </span>
    </span>
  );
}
