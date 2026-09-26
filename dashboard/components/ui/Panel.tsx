import type { ReactNode } from "react";
import { describeError } from "@/lib/errors";
import { Icon } from "./Icon";
import styles from "./ui.module.css";

export function Panel({
  id,
  eyebrow,
  title,
  actions,
  footnote,
  flush = false,
  className,
  children,
}: {
  id?: string;
  eyebrow?: ReactNode;
  title: ReactNode;
  actions?: ReactNode;
  footnote?: ReactNode;
  flush?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section id={id} className={`${styles.panel} ${className ?? ""}`} aria-labelledby={headingId}>
      <header className={styles.panelHead}>
        <div className={styles.panelHeading}>
          {eyebrow ? <p className={styles.eyebrow}>{eyebrow}</p> : null}
          <h2 id={headingId} className={styles.panelTitle}>
            {title}
          </h2>
        </div>
        {actions ? <div className={styles.panelActions}>{actions}</div> : null}
      </header>
      <div className={flush ? styles.panelFlush : styles.panelBody}>{children}</div>
      {footnote ? <footer className={styles.panelFoot}>{footnote}</footer> : null}
    </section>
  );
}

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className={styles.state} role="status" aria-live="polite">
      <span className={styles.loadingRow}>
        <Icon name="spinner" size={20} className={styles.spin} />
        {label}…
      </span>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className={styles.state}>
      <p className={styles.stateTitle}>{title}</p>
      {children ? <div>{children}</div> : null}
    </div>
  );
}

/** Shows the gate's own error message (`{"error", "message"}`). */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const info = describeError(error);
  return (
    <div className={`${styles.state} ${styles.stateError}`} role="alert">
      <p className={styles.stateErrorTitle}>
        <Icon name="error" size={20} />
        {info.title}
      </p>
      <p>{info.message}</p>
      {info.explain ? <p>{info.explain}</p> : null}
      <p className={styles.stateCode}>
        error: {info.code}
        {onRetry ? (
          <>
            {" · "}
            <button type="button" className={`${styles.button} ${styles.buttonSmall} ${styles.buttonGhost}`} onClick={onRetry}>
              Try again
            </button>
          </>
        ) : null}
      </p>
    </div>
  );
}

/** Loading, error and empty states for one SWR resource. */
export function DataState<T>({
  data,
  error,
  isLoading,
  onRetry,
  isEmpty,
  empty,
  loadingLabel,
  children,
}: {
  data: T | undefined;
  error: unknown;
  isLoading: boolean;
  onRetry?: () => void;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  loadingLabel?: string;
  children: (data: T) => ReactNode;
}) {
  if (data === undefined) {
    if (error) return <ErrorState error={error} onRetry={onRetry} />;
    if (isLoading) return <LoadingState label={loadingLabel} />;
    return <LoadingState label={loadingLabel} />;
  }
  return (
    <>
      {error ? <ErrorState error={error} onRetry={onRetry} /> : null}
      {isEmpty?.(data) ? empty : children(data)}
    </>
  );
}
