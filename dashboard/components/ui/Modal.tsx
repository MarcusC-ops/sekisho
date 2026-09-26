"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { Icon } from "./Icon";
import styles from "./ui.module.css";

/** A native <dialog> modal: focus trapping and Escape come from the browser. */
export function Modal({
  open,
  title,
  onClose,
  children,
  dismissable = true,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  dismissable?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={styles.dialog}
      aria-labelledby="modal-title"
      onCancel={(event) => {
        event.preventDefault();
        if (dismissable) onClose();
      }}
    >
      <div className={styles.dialogHead}>
        <h2 id="modal-title" className={styles.dialogTitle}>
          {title}
        </h2>
        {dismissable ? (
          <button type="button" className={styles.iconButton} onClick={onClose} aria-label="Close">
            <Icon name="close" size={18} />
          </button>
        ) : null}
      </div>
      <div className={styles.dialogBody}>{children}</div>
    </dialog>
  );
}
