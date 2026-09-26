import type { ReactNode } from "react";
import styles from "./data.module.css";

/** A named, keyboard-scrollable region keeps wide data tables inside the page. */
export function DataTable({ caption, headings, children }: { caption: string; headings: string[]; children: ReactNode }) {
  return (
    <div className={styles.tableScroll} role="region" aria-label={caption} tabIndex={0}>
      <table className={styles.table}>
        <caption className="visually-hidden">{caption}</caption>
        <thead><tr>{headings.map((heading) => <th key={heading} scope="col">{heading}</th>)}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}
