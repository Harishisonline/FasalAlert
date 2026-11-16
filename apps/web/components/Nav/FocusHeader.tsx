import Link from 'next/link';
import { LanguageSwitcher } from './LanguageSwitcher';
import { Wordmark } from './Wordmark';
import styles from './FocusHeader.module.css';

/** Minimal header for focused pages without their own (offline fallback): brand to Home and language. */
export function FocusHeader({ home, label }: { home: string; label: string }) {
  return (
    <header className={styles.bar}>
      <Link href={home} className={styles.brand} aria-label={label}><Wordmark /></Link>
      <LanguageSwitcher />
    </header>
  );
}
