'use client';
import { usePathname } from 'next/navigation';
import { useState, type ReactNode } from 'react';
import { useI18n } from '@/components/I18n';
import { SkipLink } from '@/components/UI/SkipLink';
import { destinationFor, shellFor } from '@/lib/nav';
import { BottomTabBar } from './BottomTabBar';
import { MoreDrawer } from './MoreDrawer';
import { OfflineBanner } from './OfflineBanner';
import { PublicHeader } from './PublicHeader';
import { SideNav } from './SideNav';
import { TopBar } from './TopBar';
import type { ShellData } from './types';
import styles from './AppShell.module.css';

/**
 * The one chrome for /[locale] (docs/UX_QA_AUDIT.md NAV-01):
 * - app: side nav at 1024px and up; below it a top bar (brand, language, More) and a five-tab bottom bar.
 * - focus: sign in, first-time onboarding, add field and offline bring their own back and progress controls.
 * - public: signed-out pages (regional outlook, not found) get the public header.
 */
export function AppShell({ data, children }: { data: ShellData; children: ReactNode }) {
  const { t } = useI18n();
  const pathname = usePathname();
  const kind = shellFor(pathname, data.signedIn);
  const active = destinationFor(pathname);
  const [moreOpen, setMoreOpen] = useState(false);

  if (kind === 'focus') {
    return (
      <div className={styles.focus}>
        <SkipLink href="#main">{t('skip.main')}</SkipLink>
        {children}
      </div>
    );
  }
  if (kind === 'public') {
    return (
      <div className={styles.public}>
        <SkipLink href="#main">{t('skip.main')}</SkipLink>
        <PublicHeader />
        {children}
      </div>
    );
  }
  const closeMore = () => { setMoreOpen(false); document.getElementById('more-button')?.focus(); };
  return (
    <div className={styles.frame}>
      <SkipLink href="#main">{t('skip.main')}</SkipLink>
      <SideNav data={data} active={active} pathname={pathname} />
      <div className={styles.content}>
        <TopBar onMore={() => setMoreOpen(true)} moreOpen={moreOpen} moreActive={active === 'map' || active === 'settings'} />
        <div className={styles.offline}><OfflineBanner /></div>
        {children}
      </div>
      <BottomTabBar active={active} unreadCount={data.unread} />
      <MoreDrawer open={moreOpen} onClose={closeMore} data={data} active={active} />
    </div>
  );
}
