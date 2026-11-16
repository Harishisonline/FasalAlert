'use client';
import { useId, useState, type ReactNode } from 'react';
import { ChevronDown } from '@/components/Icon';
import styles from './Disclosure.module.css';

/** "Why this?" style expander: a button with aria-expanded controlling a region (design.md 12.4 a11y). */
export function Disclosure({ label, children, defaultOpen = false, className, buttonClassName }: { label: ReactNode; children: ReactNode; defaultOpen?: boolean; className?: string; buttonClassName?: string }) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className={[styles.wrap, className ?? ''].join(' ')}>
      <button type="button" className={[styles.button, buttonClassName ?? ''].join(' ')} aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        <span>{label}</span>
        <ChevronDown size={24} aria-hidden="true" className={styles.chevron} data-open={open || undefined} />
      </button>
      <div id={id} role="region" className={styles.panel} data-open={open || undefined} hidden={!open}>
        <div className={styles.inner}>{children}</div>
      </div>
    </div>
  );
}
