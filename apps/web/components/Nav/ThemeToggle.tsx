'use client';
import { useSyncExternalStore } from 'react';
import { Moon, Sun } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { THEME_COOKIE, parseTheme, type Theme } from '@/lib/locales';
import styles from './ThemeToggle.module.css';

function subscribe(onChange: () => void) {
  const obs = new MutationObserver(onChange);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  return () => obs.disconnect();
}

function getTheme(): Theme {
  return parseTheme(document.documentElement.dataset.theme);
}

/** Light/dark toggle that writes the `theme` cookie used by the root layout (design.md 8.12). */
export function ThemeToggle() {
  const { t } = useI18n();
  const theme = useSyncExternalStore(subscribe, getTheme, () => 'light' as Theme);

  const toggle = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    document.cookie = `${THEME_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
    document.documentElement.dataset.theme = next;
  };

  const toDark = theme !== 'dark';
  return (
    <button
      type="button"
      className={styles.toggle}
      onClick={toggle}
      aria-label={toDark ? t('nav.themeToDark') : t('nav.themeToLight')}
      title={t('nav.theme')}
    >
      {toDark ? <Moon size={20} aria-hidden="true" /> : <Sun size={20} aria-hidden="true" />}
    </button>
  );
}
