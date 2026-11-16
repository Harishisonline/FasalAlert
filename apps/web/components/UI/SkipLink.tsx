import type { MouseEventHandler } from 'react';
import styles from './SkipLink.module.css';

/** The first focusable element on every page (design.md 18.2). */
export function SkipLink({ href, children, onClick }: { href: string; children: string; onClick?: MouseEventHandler<HTMLAnchorElement> }) {
  return <a href={href} className={styles.skip} onClick={onClick}>{children}</a>;
}
