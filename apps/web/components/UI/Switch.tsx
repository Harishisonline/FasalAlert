'use client';
import { useId, type ReactNode } from 'react';
import styles from './Switch.module.css';

/** A 52 x 32 switch inside a 56px row; the state is also written as text (design.md A.8). */
export function Switch({ label, description, checked, onChange, disabled, onText, offText, note, error }: {
  label: string; description?: ReactNode; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean;
  onText: string; offText: string; note?: ReactNode; error?: ReactNode;
}) {
  const id = useId();
  return (
    <div className={styles.wrap}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={`${id}-l`}
        aria-describedby={[description ? `${id}-d` : '', note ? `${id}-n` : '', error ? `${id}-e` : ''].filter(Boolean).join(' ') || undefined}
        disabled={disabled}
        className={styles.row}
        onClick={() => onChange(!checked)}
      >
        <span className={styles.text}>
          <span id={`${id}-l`} className={styles.label}>{label}</span>
          {description ? <span id={`${id}-d`} className={styles.desc}>{description}</span> : null}
        </span>
        <span className={styles.state} aria-hidden="true">{checked ? onText : offText}</span>
        <span className={styles.track} data-on={checked || undefined} aria-hidden="true"><span className={styles.thumb} /></span>
      </button>
      {note ? <p id={`${id}-n`} className={styles.note}>{note}</p> : null}
      {error ? <p id={`${id}-e`} className={styles.error} role="alert">{error}</p> : null}
    </div>
  );
}
