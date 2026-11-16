'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Bell, House, Mic, Store, Wheat } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { CountBadge } from '@/components/UI/Badges';
import type { Destination } from '@/lib/nav';
import styles from './BottomTabBar.module.css';

const TABS: { key: Destination; segment: string; Icon: typeof House; labelKey: string }[] = [
  { key: 'home', segment: 'home', Icon: House, labelKey: 'nav.home' },
  { key: 'fields', segment: 'fields', Icon: Wheat, labelKey: 'nav.fields' },
  { key: 'ask', segment: 'ask', Icon: Mic, labelKey: 'nav.ask' },
  { key: 'market', segment: 'market', Icon: Store, labelKey: 'nav.market' },
  { key: 'alerts', segment: 'alert', Icon: Bell, labelKey: 'nav.alerts' },
];

/**
 * Five labelled destinations below 1024px: Home, Fields, Ask, Market, Alerts. Plain links to separate URLs
 * (not role=tablist), so browser back works. Hidden while a text input has focus so it never covers the
 * field being typed into or sits on top of the on-screen keyboard.
 */
export function BottomTabBar({ active, unreadCount }: { active: Destination | null; unreadCount: number }) {
  const { t, locale } = useI18n();
  const [typing, setTyping] = useState(false);
  useEffect(() => {
    const isText = (el: EventTarget | null) => el instanceof HTMLElement && (el.tagName === 'TEXTAREA' || el.isContentEditable
      || (el.tagName === 'INPUT' && !['checkbox', 'radio', 'range', 'button', 'submit'].includes((el as HTMLInputElement).type)));
    const onIn = (e: FocusEvent) => setTyping(isText(e.target));
    const onOut = () => setTyping(false);
    document.addEventListener('focusin', onIn);
    document.addEventListener('focusout', onOut);
    return () => { document.removeEventListener('focusin', onIn); document.removeEventListener('focusout', onOut); };
  }, []);
  return (
    <nav aria-label={t('nav.main')} className={styles.bar} data-hidden={typing || undefined}>
      <ul className={styles.list}>
        {TABS.map(({ key, segment, Icon, labelKey }) => (
          <li key={key} className={styles.item}>
            <Link href={`/${locale}/${segment}`} className={styles.link} aria-current={active === key ? 'page' : undefined}
              aria-label={key === 'alerts' && unreadCount > 0 ? t('nav.alertsUnread', { count: unreadCount }) : undefined}>
              <span className={styles.indicator} aria-hidden="true" />
              <span className={styles.iconWrap}>
                <Icon size={24} aria-hidden="true" />
                {key === 'alerts' ? <span className={styles.badge}><CountBadge count={unreadCount} /></span> : null}
              </span>
              <span className={styles.label}>{t(labelKey)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
