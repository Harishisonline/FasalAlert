'use client';
import { useState, type ReactNode } from 'react';
import styles from './TableToggle.module.css';

export function TableToggle({ showLabel, hideLabel, children }: { showLabel: string; hideLabel: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" className={styles.toggle} aria-expanded={open} onClick={() => setOpen(!open)}>{open ? hideLabel : showLabel}</button>
      <div hidden={!open}>{children}</div>
    </div>
  );
}
