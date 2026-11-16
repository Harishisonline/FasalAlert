import type { ReactNode } from 'react';
import styles from './RouteError.module.css';

/**
 * Contain a failure to the smallest area (PRD §13 rule 2, design.md 14.25). Never a stack trace.
 * Shows the trace_id as "Error code" when present. Neutral styling: the user is not at fault.
 */
export function RouteError({ variant = 'inline', message, code, codeLabel, action }: {
  variant?: 'inline' | 'section'; message: ReactNode; code?: string | null; codeLabel?: string; action?: ReactNode;
}) {
  return (
    <div className={styles.error} data-variant={variant} role="status">
      <p className={styles.message}>{message}</p>
      {action ? <div className={styles.action}>{action}</div> : null}
      {code && codeLabel ? <p className={styles.code}>{codeLabel}</p> : null}
    </div>
  );
}
