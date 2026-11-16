import type { ReactNode } from 'react';
import styles from './Skeleton.module.css';

/** Holds the final shape while content loads (design.md 14.23). Never a spinner over content. */
export function Skeleton({ height, width = '100%', radius = 'xs', pulse = false, className }: { height: number | string; width?: number | string; radius?: 'xs' | 'md' | 'full'; pulse?: boolean; className?: string }) {
  return <span className={[styles.block, className ?? ''].join(' ')} data-radius={radius} data-pulse={pulse || undefined} style={{ height, width }} aria-hidden="true" />;
}

export function SkeletonLines({ lines = 3 }: { lines?: number }) {
  const widths = ['90%', '75%', '60%', '85%', '70%'];
  return (
    <span className={styles.lines} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => <Skeleton key={i} height="1em" width={widths[i % widths.length]} />)}
    </span>
  );
}

/** A busy region with a visually hidden "Loading" for screen readers. */
export function LoadingRegion({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div aria-busy="true" className={className}>
      <span className="visually-hidden">{label}</span>
      {children}
    </div>
  );
}
