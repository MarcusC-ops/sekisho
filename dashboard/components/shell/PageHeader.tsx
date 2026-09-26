import type { ReactNode } from "react";
import styles from "./page.module.css";

export function PageHeader({
  title,
  lede,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  lede?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <header className={styles.header}>
      <div className={styles.titles}>
        {eyebrow ? <div className={styles.eyebrow}>{eyebrow}</div> : null}
        <h1 className={styles.title}>{title}</h1>
        {lede ? <p className={styles.lede}>{lede}</p> : null}
      </div>
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </header>
  );
}

/** "Indexed by Curvegrid MultiBaas" style source captions. */
export function SourceCaption({ children }: { children: ReactNode }) {
  return <p className={styles.caption}>{children}</p>;
}
