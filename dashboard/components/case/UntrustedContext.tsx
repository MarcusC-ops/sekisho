import { Icon } from "@/components/ui/Icon";
import styles from "./case.module.css";

/**
 * Counterparty-supplied text (e.g. a vendor's response), shown verbatim as plain text.
 * It is data, never instructions: React escapes it, and the policy never reads it.
 */
export function UntrustedContext({ text }: { text: string }) {
  return (
    <section className={styles.untrusted} aria-labelledby="untrusted-title">
      <div className={styles.untrustedHead}>
        <h2 id="untrusted-title" className={styles.untrustedTitle}>
          <Icon name="alert" size={20} />
          Counterparty-supplied text
        </h2>
        <span className={styles.untrustedNote}>Untrusted data, shown verbatim. Never followed as instructions.</span>
      </div>
      <p className={styles.untrustedText}>{text}</p>
      <p className={styles.untrustedNote}>
        The agent passed this along as <code>untrusted_context</code>. The analyst may flag it; the verdict comes from the
        deterministic policy, so text like this can&apos;t change it.
      </p>
    </section>
  );
}
