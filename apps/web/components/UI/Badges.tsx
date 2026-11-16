import type { ReactNode } from 'react';
import { BadgeCheck, Timer } from '@/components/Icon';
import styles from './Badges.module.css';

/** Unread count: --color-action-primary with --color-text-on-action (design.md 11.2, A.5). */
export function CountBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return <span className={styles.count} aria-hidden="true">{count > 9 ? '9+' : count}</span>;
}

export function VerifiedTag({ label }: { label: string }) {
  return (
    <span className={styles.verified}>
      <BadgeCheck size={16} aria-hidden="true" />
      {label}
    </span>
  );
}

/** Striped "Sample data" tag for seeded synthetic data (PRD §10.1, AC 7). */
export function SampleTag({ label }: { label: string }) {
  return <span className={styles.sample}>{label}</span>;
}

export function StageChip({ children }: { children: ReactNode }) {
  return <span className={styles.stage}>{children}</span>;
}

/** The pinned "Today" label, not uppercase (design.md A.5). */
export function TodayLabel({ label }: { label: string }) {
  return (
    <span className={styles.today}>
      <Timer size={16} aria-hidden="true" />
      {label}
    </span>
  );
}
