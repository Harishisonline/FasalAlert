'use client';
import Link from 'next/link';
import { Menu } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { Wordmark } from './Wordmark';
import styles from './TopBar.module.css';

/**
 * The signed-in top bar. Below 1024px: brand (to Home) and the More button. Language, theme and help
 * live in Settings. At 1024px and up the side nav holds the brand and More's destinations.
 */
export function TopBar({ onMore, moreOpen, moreActive }: { onMore: () => void; moreOpen: boolean; moreActive: boolean }) {
  const { t, locale } = useI18n();
  return (
    <header className={styles.bar}>
      <Link href={`/${locale}/home`} className={styles.brand} aria-label={t('nav.homeBrand')}>
        <Wordmark />
      </Link>
      <div className={styles.right}>
        <button type="button" id="more-button" className={styles.more} onClick={onMore} aria-haspopup="dialog" aria-expanded={moreOpen} aria-label={t('nav.more')}
          data-active={moreActive || undefined}>
          <Menu size={24} aria-hidden="true" />
          <span className={styles.moreLabel}>{t('nav.more')}</span>
        </button>
      </div>
    </header>
  );
}
