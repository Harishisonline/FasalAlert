import type { Ref } from 'react';
import type { ReactNode } from 'react';
import { CircleCheck } from '@/components/Icon';
import styles from './EmptyState.module.css';

/** One honest line and one way forward. No illustrations (PRD §7.3, design.md 14.24). */
export function EmptyState({ variant = 'inline', icon, title, body, action, headingLevel = 2, headingRef, headingId }: {
  variant?: 'inline' | 'page' | 'positive' | 'filtered'; icon?: ReactNode; title: ReactNode; body?: ReactNode; action?: ReactNode;
  headingLevel?: 1 | 2 | 3; headingRef?: Ref<HTMLHeadingElement>; headingId?: string;
}) {
  const H = `h${headingLevel}` as 'h1' | 'h2' | 'h3';
  return (
    <div className={styles.empty} data-variant={variant}>
      {variant === 'positive' ? <CircleCheck size={24} aria-hidden="true" className={styles.positive} /> : null}
      {icon && variant === 'page' ? <span className={styles.icon}>{icon}</span> : null}
      <div className={styles.text}>
        <H className={styles.title} ref={headingRef} tabIndex={headingRef || headingId ? -1 : undefined} id={headingId}>{title}</H>
        {body ? <p className={styles.body}>{body}</p> : null}
      </div>
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}
