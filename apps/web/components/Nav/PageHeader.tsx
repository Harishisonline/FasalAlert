import Link from 'next/link';
import type { ReactNode } from 'react';
import { ArrowLeft } from '@/components/Icon';
import styles from './PageHeader.module.css';

/**
 * The page heading inside <main>: optional back link, one h1, a one-line description and the page's
 * actions (docs/UX_QA_AUDIT.md: one consistent header on every page). The shell's top bar holds brand,
 * language and navigation, so this component holds only what belongs to the page.
 */
export function PageHeader({ title, description, back, actions, eyebrow, titleId = 'page-title', meta }: {
  title: ReactNode; description?: ReactNode; back?: { href: string; label: string }; actions?: ReactNode; eyebrow?: ReactNode; titleId?: string; meta?: ReactNode;
}) {
  return (
    <header className={styles.header}>
      {back ? (
        <Link href={back.href} className={styles.back}>
          <ArrowLeft size={20} aria-hidden="true" />
          <span>{back.label}</span>
        </Link>
      ) : null}
      <div className={styles.row}>
        <div className={styles.text}>
          {eyebrow ? <p className={styles.eyebrow}>{eyebrow}</p> : null}
          <h1 id={titleId} className={styles.title}>{title}</h1>
          {description ? <p className={styles.description}>{description}</p> : null}
          {meta ? <div className={styles.meta}>{meta}</div> : null}
        </div>
        {actions ? <div className={styles.actions}>{actions}</div> : null}
      </div>
    </header>
  );
}
