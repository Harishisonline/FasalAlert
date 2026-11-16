'use client';
import Link from 'next/link';
import { useEffect, useId, useState } from 'react';
import { Menu, X } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { LanguageSwitcher } from './LanguageSwitcher';
import { ThemeToggle } from './ThemeToggle';
import { Wordmark } from './Wordmark';
import styles from './PublicHeader.module.css';

type NavLink = { href: string; label: string; key?: 'home' | 'features' | 'about' | 'how' | 'trust' };

/**
 * Header for signed-out pages and the landing page: brand, section links, language, theme, and CTA.
 * Sticky; links collapse into a drawer below 960px.
 */
export function PublicHeader({ links = [], languageMode = 'path' }: {
  links?: { href: string; label: string; key?: NavLink['key'] }[]; languageMode?: 'path' | 'query';
}) {
  const { t, locale } = useI18n();
  const menuId = useId();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const homeHref = languageMode === 'query' ? '/' : `/?lang=${locale}`;
  // The landing page only leads to sign-in: no links into the app (Regional outlook needs an account).
  const defaults: NavLink[] = [{ href: homeHref, label: t('landing.nav.home'), key: 'home' }, ...links];

  const close = () => setOpen(false);

  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <Link href={homeHref} className={styles.brand} aria-label={t('nav.landing')} onClick={close}>
          <Wordmark wordFromWide />
        </Link>
        <nav aria-label={t('nav.public')} className={styles.links}>
          <ul>
            {defaults.map((l) => (
              <li key={l.href}>
                <a
                  href={l.href}
                  className={styles.link}
                >
                  {l.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className={styles.right}>
          {/* Below 520 px these move into the menu so the header fits a 360 px phone. */}
          <div className={styles.prefs}>
            <ThemeToggle />
            <LanguageSwitcher mode={languageMode} />
          </div>
          <Link href={`/${locale}/signin`} className={styles.cta}><span>{t('landing.signIn')}</span></Link>
          <button
            type="button"
            className={styles.menuBtn}
            aria-expanded={open}
            aria-controls={menuId}
            aria-label={t('nav.menu')}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <X size={22} aria-hidden="true" /> : <Menu size={22} aria-hidden="true" />}
          </button>
        </div>
      </div>
      {open ? (
        <nav id={menuId} className={styles.drawer} aria-label={t('nav.public')}>
          <ul>
            {defaults.map((l) => (
              <li key={`m-${l.href}`}>
                <a href={l.href} className={styles.drawerLink} onClick={close}>{l.label}</a>
              </li>
            ))}
            <li className={styles.drawerPrefs}>
              <LanguageSwitcher mode={languageMode} />
              <ThemeToggle />
            </li>
            <li>
              <Link href={`/${locale}/signin`} className={styles.drawerCta} onClick={close}>{t('landing.signIn')}</Link>
            </li>
          </ul>
        </nav>
      ) : null}
    </header>
  );
}
