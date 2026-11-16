'use client';
import { useEffect, useId, useRef, type ReactNode } from 'react';
import styles from './Dialog.module.css';

/**
 * Confirmation dialog on native <dialog> (design.md A.12). A bottom sheet below 768px, centred above.
 * Focus moves to the heading; Escape and the scrim cancel.
 */
export function Dialog({ open, title, children, onCancel, actions }: { open: boolean; title: string; children?: ReactNode; onCancel: () => void; actions: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const id = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      headingRef.current?.focus();
    } else if (!open && d.open) {
      d.close();
    }
  }, [open]);
  return (
    <dialog
      ref={ref}
      className={styles.dialog}
      aria-labelledby={`${id}-t`}
      onCancel={(e) => { e.preventDefault(); onCancel(); }}
      onClick={(e) => { if (e.target === ref.current) onCancel(); }}
    >
      <div className={styles.body}>
        <h2 id={`${id}-t`} ref={headingRef} tabIndex={-1} className={styles.title}>{title}</h2>
        {children ? <div className={styles.content}>{children}</div> : null}
        <div className={styles.actions}>{actions}</div>
      </div>
    </dialog>
  );
}
