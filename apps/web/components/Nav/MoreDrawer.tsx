'use client';
import Link from 'next/link';
import type { ReactNode } from 'react';
import { ChevronRight, LogOut, MapIcon, Settings, SlidersHorizontal } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { Sheet } from '@/components/UI/Sheet';
import { signOut } from '@/lib/auth-client';
import type { Destination } from '@/lib/nav';
import { SocialLinks } from './SocialLinks';
import type { ShellData } from './types';
import styles from './MoreDrawer.module.css';

/**
 * The mobile More sheet (below 1024px): Regional outlook, account pages and sign out.
 * Language, theme and help live in Settings.
 */
export function MoreDrawer({ open, onClose, data, active }: { open: boolean; onClose: () => void; data: ShellData; active: Destination | null }) {
  const { t, locale } = useI18n();
  const row = (key: string, href: string, icon: ReactNode, label: string, current = false) => (
    <li key={key}>
      <Link href={href} className={styles.row} onClick={onClose} aria-current={current ? 'page' : undefined}>
        {icon}<span className={styles.text}>{label}</span><ChevronRight size={20} aria-hidden="true" />
      </Link>
    </li>
  );
  return (
    <Sheet open={open} onClose={onClose} title={t('nav.more')} expandLabel={t('nav.expand')} collapseLabel={t('nav.collapse')} closeLabel={t('nav.close')}>
      <section aria-labelledby="more-explore" className={styles.section}>
        <h3 id="more-explore" className={styles.heading}>{t('nav.explore')}</h3>
        <ul className={styles.list}>
          {row('map', `/${locale}/map`, <MapIcon size={24} aria-hidden="true" />, t('nav.map'), active === 'map')}
        </ul>
      </section>
      <section aria-labelledby="more-account" className={styles.section}>
        <h3 id="more-account" className={styles.heading}>{t('nav.account')}</h3>
        {data.user ? (
          <p className={styles.who}>
            {data.user.name ? <span className={styles.name}>{data.user.name}</span> : null}
            <span className={styles.meta}>{data.user.phoneMasked}</span>
          </p>
        ) : null}
        <ul className={styles.list}>
          {row('settings', `/${locale}/settings`, <Settings size={24} aria-hidden="true" />, t('nav.settings'), active === 'settings')}
          {row('calibration', `/${locale}/settings/calibration`, <SlidersHorizontal size={24} aria-hidden="true" />, t('nav.calibration'))}
        </ul>
      </section>
      <section className={styles.section}>
        <button type="button" className={styles.row} data-danger onClick={() => void signOut(locale)}>
          <LogOut size={24} aria-hidden="true" /><span className={styles.text}>{t('nav.signOut')}</span>
        </button>
      </section>
      <footer className={styles.footer}>
        <p className={styles.meta}>{t('nav.credits')}</p>
        <SocialLinks t={t} />
      </footer>
    </Sheet>
  );
}
