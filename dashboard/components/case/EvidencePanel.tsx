import { Address } from "@/components/ui/Address";
import { Icon } from "@/components/ui/Icon";
import { Panel } from "@/components/ui/Panel";
import { LiveTag, Tag } from "@/components/ui/Pills";
import { chainName } from "@/lib/config";
import { formatMs } from "@/lib/format";
import type { CaseDetail, Check, QuickScanEvidence, QuickScanTrait, TraitClass } from "@/lib/types";
import { TRAIT_CLASS_LABEL } from "@/lib/vocab";
import styles from "./case.module.css";

const CLASS_ORDER: Record<TraitClass, number> = { hard_block: 0, hold: 1, other: 2, info: 3 };
const CLASS_TONE: Record<TraitClass, string> = { hard_block: "block", hold: "hold", other: "neutral", info: "neutral" };

function sortTraits(traits: QuickScanTrait[]): QuickScanTrait[] {
  return [...traits].sort((a, b) => CLASS_ORDER[a.class] - CLASS_ORDER[b.class] || b.risk - a.risk);
}

function checkMeta(check: Check | undefined) {
  if (!check) return null;
  return (
    <span className={styles.subheadMeta} style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
      <LiveTag live={check.live} />
      {formatMs(check.latency_ms)}
      {check.evidence_id ? ` · ${check.evidence_id}` : ""}
    </span>
  );
}

function TraitsTable({ scan, caption }: { scan: QuickScanEvidence; caption: string }) {
  const traits = sortTraits(scan.traits ?? []);
  if (!traits.length) {
    return <p className={styles.muted}>No risk traits reported (toxicScore {scan.toxicScore}).</p>;
  }
  return (
    <>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <caption className="visually-hidden">{caption}</caption>
          <thead>
            <tr>
              <th scope="col">Trait</th>
              <th scope="col">Class</th>
              <th scope="col" className={styles.num}>
                Risk
              </th>
              <th scope="col" className={styles.num}>
                Txs
              </th>
              <th scope="col">Intercepta description (verbatim)</th>
            </tr>
          </thead>
          <tbody>
            {traits.map((t) => (
              <tr key={t.name} className={t.class === "info" ? styles.rowInfo : undefined}>
                <td className={styles.traitName}>{t.name}</td>
                <td>
                  <span className={styles.classChip} data-tone={CLASS_TONE[t.class]}>
                    {t.class === "hard_block" ? <Icon name="block" size={14} strokeWidth={2.6} /> : t.class === "hold" ? <Icon name="hold" size={14} strokeWidth={2.6} /> : null}
                    {TRAIT_CLASS_LABEL[t.class] ?? t.class}
                  </span>
                </td>
                <td className={styles.num}>{t.risk}</td>
                <td className={styles.num}>{t.txsCount}</td>
                <td>
                  <q className={styles.verbatim}>{t.description}</q>
                  {t.class === "info" ? <span className={styles.muted}> Shown for information; it doesn&apos;t change the verdict.</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={styles.caption}>
        Descriptions are Intercepta&apos;s own text, shown verbatim. Info-only traits usually mean the wallet received spam or
        poisoning dust, so the demo policy doesn&apos;t penalise them.
      </p>
    </>
  );
}

export function EvidencePanel({ c }: { c: CaseDetail }) {
  const { evidence } = c;
  const byName = (name: string) => c.checks.find((k) => k.name === name);
  const qsCheck = byName("intercepta.quick_scan");
  const oracleCheck = byName("sanctions.oracle");
  const impCheck = byName("intercepta.impersonation");
  const tokenCheck = byName("intercepta.token");
  const deepCheck = byName("intercepta.deep_scan");

  return (
    <Panel id="evidence" eyebrow="What the checks returned" title="Evidence">
      <section id="evidence-quick-scan" className={styles.section}>
        <h3 className={styles.subhead}>
          Intercepta Quick Scan
          {evidence.quick_scan ? <Tag variant="solid">toxicScore {evidence.quick_scan.toxicScore}</Tag> : null}
          {checkMeta(qsCheck)}
        </h3>
        {evidence.quick_scan ? (
          <TraitsTable scan={evidence.quick_scan} caption="Intercepta Quick Scan traits" />
        ) : (
          <div className={styles.revert} role="note">
            <span className={styles.revertTitle}>
              <Icon name="error" size={18} />
              Quick Scan failed: {qsCheck?.error ?? qsCheck?.summary ?? "no data"}
            </span>
            <span>The policy failed closed (screening_error): missing data is never an ALLOW.</span>
          </div>
        )}
      </section>

      <section className={styles.section}>
        <div className={styles.miniGrid}>
          <div id="evidence-oracle" className={styles.miniCard}>
            <span className={styles.miniTitle}>Chainalysis sanctions oracle</span>
            {checkMeta(oracleCheck)}
            {evidence.oracle ? (
              Object.entries(evidence.oracle).map(([chainId, sanctioned]) => (
                <span key={chainId} className={styles.result} data-tone={sanctioned ? "block" : undefined}>
                  <Icon name={sanctioned ? "block" : "check"} size={18} strokeWidth={2.4} />
                  {chainName(Number(chainId))}: {sanctioned ? "sanctioned" : "not listed"}
                </span>
              ))
            ) : (
              <span className={styles.muted}>{oracleCheck?.error ?? "No oracle result."}</span>
            )}
            <span className={styles.muted}>isSanctioned() on mainnet, read-only.</span>
          </div>

          <div id="evidence-impersonation" className={styles.miniCard}>
            <span className={styles.miniTitle}>Intercepta impersonation check</span>
            {checkMeta(impCheck)}
            {evidence.impersonation ? (
              evidence.impersonation.isAddressPoisoned ? (
                <span className={styles.result} data-tone="block">
                  <Icon name="block" size={18} strokeWidth={2.4} />
                  Address-poisoning lookalike
                  {evidence.impersonation.originalAddress ? (
                    <>
                      {" "}
                      of <Address address={evidence.impersonation.originalAddress} />
                    </>
                  ) : null}
                </span>
              ) : (
                <span className={styles.result}>
                  <Icon name="check" size={18} strokeWidth={2.4} />
                  Not a poisoning lookalike
                </span>
              )
            ) : (
              <span className={styles.muted}>{impCheck ? `Unavailable: ${impCheck.error ?? impCheck.summary}` : "Not run for this case."}</span>
            )}
          </div>

          <div id="evidence-token" className={styles.miniCard}>
            <span className={styles.miniTitle}>Payment token scan</span>
            {checkMeta(tokenCheck)}
            {evidence.token_scan ? (
              <>
                <span className={styles.result} data-tone={evidence.token_scan.action === "block" ? "block" : evidence.token_scan.action === "warn" ? "hold" : undefined}>
                  <Icon name={evidence.token_scan.action === "info" ? "check" : "alert"} size={18} strokeWidth={2.4} />
                  Action {evidence.token_scan.action}
                </span>
                <span className={styles.muted}>
                  riskScore {evidence.token_scan.riskScore} · riskLevel {evidence.token_scan.riskLevel}
                </span>
                <span className={styles.muted}>Scanned as its Base mainnet equivalent.</span>
              </>
            ) : (
              <span className={styles.muted}>{tokenCheck ? `Unavailable: ${tokenCheck.error ?? tokenCheck.summary}` : "Not run for this case."}</span>
            )}
          </div>
        </div>
      </section>

      {evidence.deep_scan ? (
        <section id="evidence-deep-scan" className={styles.section}>
          <h3 className={styles.subhead}>
            Intercepta Deep Scan <Tag>After HOLD</Tag>
            <Tag variant="solid">toxicScore {evidence.deep_scan.toxicScore}</Tag>
            {checkMeta(deepCheck)}
          </h3>
          <TraitsTable scan={evidence.deep_scan} caption="Intercepta Deep Scan traits" />
        </section>
      ) : null}

      <section className={styles.section}>
        <details className={styles.details}>
          <summary>
            <Icon name="eye" size={18} />
            Raw check responses
          </summary>
          <pre className={styles.raw}>{JSON.stringify(evidence, null, 2)}</pre>
        </details>
      </section>
    </Panel>
  );
}
