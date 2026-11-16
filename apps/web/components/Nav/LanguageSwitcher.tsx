'use client';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useT, useI18n } from '@/components/I18n';
import { useToast } from '@/components/UI/Toast';
import { clientApi } from '@/lib/client-api';
import { CHIP_LABELS, LOCALES, NATIVE_NAMES, type Locale } from '@/lib/locales';
import styles from './LanguageSwitcher.module.css';

export function swapLocale(pathname: string, locale: Locale): string {
  const parts = pathname.split('/');
  if (parts.length > 1 && (LOCALES as readonly string[]).includes(parts[1] ?? '')) parts[1] = locale;
  else parts.splice(1, 0, locale);
  return parts.join('/') || '/';
}

/**
 * Three chips, always visible in the header (PRD §14.3, design.md 14.20). Labels are native names,
 * never translated, with lang and hreflang. R1 swaps ?lang=; other routes swap the locale segment.
 */
export function LanguageSwitcher({ mode = 'path', signedIn = false }: { mode?: 'path' | 'query'; signedIn?: boolean }) {
  const { locale } = useI18n();
  const t = useT();
  const pathname = usePathname();
  const params = useSearchParams();
  const router = useRouter();
  const toast = useToast();

  const hrefFor = (l: Locale) => {
    const q = new URLSearchParams(params.toString());
    if (mode === 'query') {
      q.set('lang', l);
      return `${pathname}?${q.toString()}`;
    }
    const qs = q.toString();
    return `${swapLocale(pathname, l)}${qs ? `?${qs}` : ''}`;
  };

  const persist = async (l: Locale) => {
    if (!signedIn || (typeof navigator !== 'undefined' && !navigator.onLine)) return;
    const r = await clientApi('users/me', { method: 'PATCH', body: { preferred_locale: l } });
    if (!r.ok && r.kind === 'http' && r.status !== 401) {
      // The server disagrees: revert to the previous language (PRD §7.9).
      toast(t('settings.langFailed'));
      router.replace(hrefFor(locale), { scroll: false });
    }
  };

  return (
    <nav aria-label={t('lang.label')} className={styles.switcher}>
      <ul className={styles.list}>
        {LOCALES.map((l) => (
          <li key={l}>
            <Link
              href={hrefFor(l)}
              scroll={false}
              replace={mode === 'query'}
              lang={l}
              hrefLang={l}
              aria-current={l === locale ? 'true' : undefined}
              aria-label={l === 'en' ? `${CHIP_LABELS.en}, ${NATIVE_NAMES.en}` : undefined}
              className={styles.chip}
              onClick={() => {
                document.cookie = `NEXT_LOCALE=${l}; path=/; max-age=31536000; samesite=lax`;
                if (l !== locale) void persist(l);
              }}
            >
              {CHIP_LABELS[l]}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** The radio-card variant for R2 step 3 and R9a (design.md 14.20). */
export function LanguageRadioCards({ value, onChange, legend, disabled, name = 'language' }: { value: Locale; onChange: (l: Locale) => void; legend: string; disabled?: boolean; name?: string }) {
  const order: Locale[] = ['mr', 'hi', 'en'];
  return (
    <fieldset className={styles.cards} disabled={disabled}>
      <legend className="visually-hidden">{legend}</legend>
      {order.map((l) => (
        <label key={l} className={styles.card} data-checked={value === l || undefined}>
          <input type="radio" name={name} value={l} checked={value === l} onChange={() => onChange(l)} className={styles.radio} />
          <span lang={l} className={styles.cardLabel}>{NATIVE_NAMES[l]}</span>
        </label>
      ))}
    </fieldset>
  );
}
