import { LogoMark } from '@/components/Icon';
import styles from './Wordmark.module.css';

/** Logo mark and wordmark (design.md 5.1, 5.2). Below 400px only the mark shows (fix 14). */
export function Wordmark({ showDevanagari, devanagari, alwaysWord, wordFromWide, markOnly }: {
  showDevanagari?: boolean; devanagari?: string; alwaysWord?: boolean; wordFromWide?: boolean; markOnly?: boolean;
}) {
  return (
    <span className={styles.brand} data-always={alwaysWord || undefined} data-wide={wordFromWide || undefined} data-mark={markOnly || undefined}>
      <LogoMark size={32} />
      <span className={styles.word} lang="en" aria-hidden="true">
        <span className={styles.fasal}>Fasal</span><span className={styles.alert}>Alert</span>
      </span>
      {showDevanagari && !markOnly && devanagari ? <span className={styles.deva} lang="hi">{devanagari}</span> : null}
      <span className="visually-hidden">FasalAlert</span>
    </span>
  );
}
