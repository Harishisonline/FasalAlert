import type { Locale } from '@fasalalert/shared/api';

export type { Locale };

export const LOCALES: readonly Locale[] = ['en', 'mr', 'hi'] as const;
/** Schema default (PRD §10, design.md 10.1). */
export const DEFAULT_LOCALE: Locale = 'mr';
export const LOCALE_COOKIE = 'NEXT_LOCALE';
export const THEME_COOKIE = 'theme';

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (LOCALES as readonly string[]).includes(value);
}

/** Western digits in every locale (design.md 7.5, D-17). Never plain 'mr-IN'. */
export function intlLocale(locale: Locale): string {
  return `${locale}-IN-u-nu-latn`;
}

/** Native language names, never translated (design.md 14.20). */
export const NATIVE_NAMES: Record<Locale, string> = { en: 'English', mr: 'मराठी', hi: 'हिंदी' };
export const CHIP_LABELS: Record<Locale, string> = { en: 'EN', mr: 'मराठी', hi: 'हिंदी' };

/** Pick a supported locale from an Accept-Language header, or null. */
export function matchAcceptLanguage(header: string | null | undefined): Locale | null {
  if (!header) return null;
  const ranked = header
    .split(',')
    .map((part) => {
      const [tag, ...params] = part.trim().split(';');
      const q = params.find((p) => p.trim().startsWith('q='));
      return { tag: (tag ?? '').toLowerCase(), q: q ? Number(q.trim().slice(2)) || 0 : 1 };
    })
    .filter((x) => x.tag)
    .sort((a, b) => b.q - a.q);
  for (const { tag } of ranked) {
    const base = tag.split('-')[0];
    if (isLocale(base)) return base;
  }
  return null;
}

export type Theme = 'light' | 'dark';
export function parseTheme(value: string | undefined | null): Theme {
  return value === 'dark' ? 'dark' : 'light';
}
