'use client';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Info } from '@/components/Icon';
import styles from './Toggletip.module.css';

/** A tap-to-open explanation, never hover-only (design.md A.14). */
export function Toggletip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: PointerEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('pointerdown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('pointerdown', onDoc); document.removeEventListener('keydown', onKey); };
  }, [open]);
  return (
    <span ref={ref} className={styles.wrap}>
      <button type="button" className={styles.button} aria-label={label} aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        <Info size={20} aria-hidden="true" />
      </button>
      <span id={id} role="status" className={styles.pop} hidden={!open}>{open ? children : null}</span>
    </span>
  );
}
