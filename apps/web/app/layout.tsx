import type { Metadata, Viewport } from 'next';
import { cookies, headers } from 'next/headers';
import type { ReactNode } from 'react';
import { PwaRegister } from '@/components/PwaRegister';
import { createTranslator } from '@/lib/i18n';
import { DEFAULT_LOCALE, THEME_COOKIE, isLocale, parseTheme } from '@/lib/locales';
import { inter, notoDeva } from './fonts';
import '@/styles/tokens.css';
import '@/styles/globals.css';

export async function generateMetadata(): Promise<Metadata> {
  const h = await headers();
  const raw = h.get('x-fa-locale');
  const t = createTranslator(isLocale(raw) ? raw : DEFAULT_LOCALE);
  return {
    title: { default: t('meta.title'), template: `%s · ${t('meta.title')}` },
    description: t('meta.description'),
    applicationName: 'FasalAlert',
    metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || 'http://localhost:3000'),
    icons: {
      icon: [
        { url: '/icons/icon.svg', type: 'image/svg+xml' },
        { url: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
      ],
      apple: [{ url: '/icons/apple-touch-icon.png', sizes: '180x180' }],
    },
    appleWebApp: { capable: true, title: 'FasalAlert', statusBarStyle: 'default' },
    formatDetection: { telephone: false },
  };
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#0b5c2e',
};

/**
 * Root layout: fonts, tokens, <html lang> from the locale computed by proxy.ts, and the theme from the
 * `theme` cookie so the first paint is right (design.md 8.12). Light by default, no system mode.
 */
export default async function RootLayout({ children }: { children: ReactNode }) {
  const h = await headers();
  const c = await cookies();
  const raw = h.get('x-fa-locale');
  const locale = isLocale(raw) ? raw : DEFAULT_LOCALE;
  const theme = parseTheme(c.get(THEME_COOKIE)?.value);
  return (
    <html lang={locale} data-theme={theme} className={`${inter.variable} ${notoDeva.variable}`} suppressHydrationWarning>
      <body>
        <PwaRegister>{children}</PwaRegister>
      </body>
    </html>
  );
}
