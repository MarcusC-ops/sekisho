import { DIRECTION_HELP, DIRECTION_LABEL, SOURCE_LABEL, STATUS_LABEL } from "@/lib/vocab";
import { shortHash } from "@/lib/format";
import type { Attestation, CaseStatus, Direction, Source } from "@/lib/types";
import { Icon } from "./Icon";
import styles from "./ui.module.css";

export function StatusChip({ status }: { status: CaseStatus }) {
  return (
    <span className={styles.statusChip} title={`Case status: ${status}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

/** "→ paying" / "← being paid" */
export function DirectionLabel({ direction }: { direction: Direction }) {
  return (
    <span className={styles.direction} title={DIRECTION_HELP[direction]}>
      <Icon name={direction === "outbound" ? "arrowRight" : "arrowLeft"} size={17} strokeWidth={2.4} />
      {DIRECTION_LABEL[direction]}
    </span>
  );
}

export function Tag({ children, variant, title }: { children: React.ReactNode; variant?: "live" | "solid"; title?: string }) {
  const cls = variant === "live" ? styles.tagLive : variant === "solid" ? styles.tagSolid : "";
  return (
    <span className={`${styles.tag} ${cls}`} title={title}>
      {children}
    </span>
  );
}

export function SourceTag({ source }: { source: Source | null | undefined }) {
  if (!source) return null;
  const title =
    source === "x402" ? "Screened inside an x402 payment" : source === "mcp" ? "Screened through the MCP tool" : "Direct transfer (pay_invoice)";
  return <Tag title={title}>{SOURCE_LABEL[source] ?? source}</Tag>;
}

/** Live/cached marker for checks that call Intercepta (null means not applicable). */
export function LiveTag({ live }: { live: boolean | null | undefined }) {
  if (live === true) {
    return (
      <Tag variant="live" title="Fresh Intercepta call for this decision">
        Live
      </Tag>
    );
  }
  if (live === false) return <Tag title="Served from the 24 h cache">Cached</Tag>;
  return null;
}

/** Attestation of the verdict onchain: queued → submitted → confirmed (tx link) or failed. */
export function AttestationPill({ attestation, compact = false }: { attestation: Attestation; compact?: boolean }) {
  const { status, tx_hash, explorer_url, error } = attestation;
  if (status === "confirmed" && tx_hash) {
    return (
      <a
        className={styles.pill}
        data-tone="accent"
        href={explorer_url || undefined}
        target="_blank"
        rel="noreferrer"
        title={`Screened event confirmed onchain: ${tx_hash}`}
        onClick={(e) => e.stopPropagation()}
        style={{ position: "relative", zIndex: 1 }}
      >
        <Icon name="chain" size={16} />
        {compact ? "Attested" : `Attested ${shortHash(tx_hash)}`}
        <Icon name="external" size={14} />
      </a>
    );
  }
  if (status === "submitted") {
    return (
      <span className={styles.pill} data-tone="accent" title={tx_hash ? `Submitted: ${tx_hash}` : "Submitted"}>
        <Icon name="spinner" size={16} className={styles.spin} />
        Attesting
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className={styles.pill} data-state="failed" title={error ?? "Attestation failed"}>
        <Icon name="error" size={16} />
        Attestation failed
      </span>
    );
  }
  return (
    <span className={styles.pill} data-tone="neutral" title="Queued for recordScreening via MultiBaas">
      <Icon name="clock" size={16} />
      Attestation queued
    </span>
  );
}
