import type { ReactNode } from 'react';
import styles from './Page.module.css';

/** The main landmark with the page width rules (design.md 8.6, 13.2). */
export function PageMain({ width = 'max', children, renderedAt, className, fab }: { width?: 'max' | 'reading' | 'narrow'; children: ReactNode; renderedAt?: string; className?: string; fab?: boolean }) {
  return (
    <main id="main" tabIndex={-1} className={[styles.main, className ?? ''].join(' ')} data-width={width} data-fab={fab || undefined} data-rendered-at={renderedAt}>
      {children}
    </main>
  );
}

export function Section({ title, id, children, action, className, headingLevel = 2 }: { title: ReactNode; id: string; children: ReactNode; action?: ReactNode; className?: string; headingLevel?: 2 | 3 }) {
  const H = `h${headingLevel}` as 'h2' | 'h3';
  return (
    <section className={[styles.section, className ?? ''].join(' ')} aria-labelledby={id}>
      <div className={styles.sectionHead}>
        <H id={id} className={styles.sectionTitle}>{title}</H>
        {action}
      </div>
      {children}
    </section>
  );
}
