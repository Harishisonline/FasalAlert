'use client';
import Link from 'next/link';
import { useEffect, useId, useSyncExternalStore, type ReactNode } from 'react';
import {
  Bell, CropIcon, House, MapIcon, Mic, PanelLeft, PanelLeftClose, Plus, Settings, SlidersHorizontal, Store, Wheat,
} from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { CountBadge } from '@/components/UI/Badges';
import type { Destination } from '@/lib/nav';
import { ProfileMenu } from './ProfileMenu';
import { Wordmark } from './Wordmark';
import type { ShellData } from './types';
import styles from './SideNav.module.css';

const QUICK_FIELDS = 5;
const COLLAPSE_KEY = 'fa-sidebar-collapsed';

function subscribeCollapse(onChange: () => void) {
  window.addEventListener('storage', onChange);
  window.addEventListener('fa-sidebar', onChange);
  return () => {
    window.removeEventListener('storage', onChange);
    window.removeEventListener('fa-sidebar', onChange);
  };
}

function readCollapsed(): boolean {
  try { return localStorage.getItem(COLLAPSE_KEY) === '1'; } catch { return false; }
}

function writeCollapsed(next: boolean) {
  try { localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0'); } catch { /* private mode */ }
  window.dispatchEvent(new Event('fa-sidebar'));
}

/**
 * Desktop navigation, 1024px and up (docs/UX_QA_AUDIT.md NAV-01): overview, farm tools, quick fields,
 * then account. Collapsible; preference persists in localStorage. Labels become tooltips when collapsed.
 */
export function SideNav({ data, active, pathname }: { data: ShellData; active: Destination | null; pathname: string }) {
  const { t, locale } = useI18n();
  const collapseId = useId();
  const collapsed = useSyncExternalStore(subscribeCollapse, readCollapsed, () => false);

  useEffect(() => {
    document.documentElement.dataset.sidebar = collapsed ? 'collapsed' : 'expanded';
    return () => { delete document.documentElement.dataset.sidebar; };
  }, [collapsed]);

  const toggle = () => writeCollapsed(!collapsed);

  const item = (key: string, href: string, current: boolean, Icon: typeof House, label: string, extra?: ReactNode, aria?: string) => (
    <li key={key}>
      <Link
        href={href}
        className={styles.item}
        aria-current={current ? 'page' : undefined}
        aria-label={aria ?? (collapsed ? label : undefined)}
        title={collapsed ? label : undefined}
      >
        <Icon size={22} aria-hidden="true" />
        <span className={styles.label}>{label}</span>
        {extra}
      </Link>
    </li>
  );

  const fields = data.fields.slice(0, QUICK_FIELDS);
  const onSettings = pathname === `/${locale}/settings` || pathname === `/${locale}/settings/`;
  const onCalib = pathname.startsWith(`/${locale}/settings/calibration`);

  return (
    <aside className={styles.side} data-collapsed={collapsed || undefined} aria-labelledby={collapseId}>
      <div className={styles.top}>
        <Link href={`/${locale}/home`} className={styles.brand} aria-label={t('nav.homeBrand')}>
          <Wordmark alwaysWord={!collapsed} markOnly={collapsed} />
        </Link>
        <button
          type="button"
          id={collapseId}
          className={styles.collapse}
          onClick={toggle}
          aria-pressed={collapsed}
          aria-label={collapsed ? t('nav.expandSidebar') : t('nav.collapseSidebar')}
          title={collapsed ? t('nav.expandSidebar') : t('nav.collapseSidebar')}
        >
          {collapsed ? <PanelLeft size={20} aria-hidden="true" /> : <PanelLeftClose size={20} aria-hidden="true" />}
        </button>
      </div>
      <nav aria-label={t('nav.main')} className={styles.nav}>
        <p className={styles.groupTitle} id="nav-overview">{t('nav.overview')}</p>
        <ul className={styles.group} aria-labelledby="nav-overview">
          {item('home', `/${locale}/home`, active === 'home', House, t('nav.home'))}
          {item('map', `/${locale}/map`, active === 'map', MapIcon, t('nav.map'))}
        </ul>

        <p className={styles.groupTitle} id="nav-farm">{t('nav.farm')}</p>
        <ul className={styles.group} aria-labelledby="nav-farm">
          {item('fields', `/${locale}/fields`, active === 'fields', Wheat, t('nav.fields'))}
          {!collapsed && data.fields.length ? (
            <li key="field-subs">
              <ul className={styles.subList} aria-label={t('nav.myFields')}>
                {fields.map((f) => (
                  <li key={f.id}>
                    <Link
                      href={`/${locale}/field/${f.id}`}
                      className={styles.subItem}
                      aria-current={pathname === `/${locale}/field/${f.id}` ? 'page' : undefined}
                      title={f.name}
                    >
                      <CropIcon crop={f.crop} size={20} />
                      <span className={styles.subLabel}>{f.name}</span>
                    </Link>
                  </li>
                ))}
                {data.fields.length > QUICK_FIELDS ? (
                  <li key="all-fields">
                    <Link href={`/${locale}/fields`} className={styles.subItem}>
                      <span className={styles.subLabel}>{t('nav.allFields', { count: data.fields.length })}</span>
                    </Link>
                  </li>
                ) : null}
                <li key="add-field">
                  <Link href={`/${locale}/fields/new`} className={styles.subItem}>
                    <Plus size={20} aria-hidden="true" />
                    <span className={styles.subLabel}>{t('nav.addField')}</span>
                  </Link>
                </li>
              </ul>
            </li>
          ) : null}
          {item('ask', `/${locale}/ask`, active === 'ask', Mic, t('nav.askLong'))}
          {item('market', `/${locale}/market`, active === 'market', Store, t('nav.market'))}
          {item(
            'alerts',
            `/${locale}/alert`,
            active === 'alerts',
            Bell,
            t('nav.alerts'),
            <CountBadge count={data.unread} />,
            data.unread > 0 ? t('nav.alertsUnread', { count: data.unread }) : undefined,
          )}
        </ul>

        <p className={styles.groupTitle} id="nav-account">{t('nav.account')}</p>
        <ul className={styles.group} aria-labelledby="nav-account">
          {item('settings', `/${locale}/settings`, onSettings, Settings, t('nav.settings'))}
          {item('calibration', `/${locale}/settings/calibration`, onCalib, SlidersHorizontal, t('nav.calibration'))}
        </ul>
      </nav>
      {data.user && !collapsed ? <div className={styles.profile}><ProfileMenu name={data.user.name} phoneMasked={data.user.phoneMasked} /></div> : null}
    </aside>
  );
}
