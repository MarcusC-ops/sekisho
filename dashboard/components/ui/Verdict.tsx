import { VERDICT_META } from "@/lib/vocab";
import type { Verdict } from "@/lib/types";
import { Icon, type IconName } from "./Icon";
import styles from "./ui.module.css";

const ICON: Record<Verdict, IconName> = { ALLOW: "allow", HOLD: "hold", BLOCK: "block" };

export function verdictTone(verdict: Verdict) {
  return VERDICT_META[verdict].tone;
}

export function VerdictIcon({ verdict, size = 18 }: { verdict: Verdict; size?: number }) {
  return <Icon name={ICON[verdict]} size={size} strokeWidth={2.4} />;
}

/** Verdict as icon + label (never colour alone). */
export function VerdictChip({ verdict, large = false }: { verdict: Verdict; large?: boolean }) {
  return (
    <span className={`${styles.chip} ${large ? styles.chipLarge : ""}`} data-tone={verdictTone(verdict)}>
      <VerdictIcon verdict={verdict} size={large ? 20 : 17} />
      {VERDICT_META[verdict].label}
    </span>
  );
}

/**
 * The checkpoint's stamp: verdict kanji (通 pass, 留 hold, 止 stop) over the verdict label.
 * The kanji is decorative; the label and icon carry the meaning.
 */
export function VerdictSeal({ verdict, small = false, stamp = false }: { verdict: Verdict; small?: boolean; stamp?: boolean }) {
  const meta = VERDICT_META[verdict];
  return (
    <div
      className={`${styles.seal} ${small ? styles.sealSmall : ""} ${stamp ? styles.stamp : ""}`}
      data-tone={meta.tone}
      role="img"
      aria-label={`Verdict: ${meta.label}. ${meta.meaning}.`}
    >
      <span className={styles.sealKanji} aria-hidden="true" lang="ja">
        {meta.kanji}
      </span>
      <span className={styles.sealLabel} aria-hidden="true">
        <VerdictIcon verdict={verdict} size={small ? 13 : 16} />
        {meta.label}
      </span>
    </div>
  );
}
