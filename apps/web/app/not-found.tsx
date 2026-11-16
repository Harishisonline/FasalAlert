import { headers } from 'next/headers';
import { I18nProvider } from '@/components/I18n';
import { AppShell } from '@/components/Nav/AppShell';
import { NotFoundView } from '@/components/System/NotFoundView';
import { ToastProvider } from '@/components/UI/Toast';
import { createTranslator, getMessages } from '@/lib/i18n';
import { DEFAULT_LOCALE, isLocale } from '@/lib/locales';
import { loadShellData } from '@/lib/shell';

/**
 * Root 404 for unmatched URLs (design.md 10.1, Appendix B Q25). A framework special file, not a route:
 * it re-uses the R12 view, with the locale taken from the first path segment or the NEXT_LOCALE cookie
 * (resolved in proxy.ts as x-fa-locale).
 */
export default async function RootNotFound() {
  const raw = (await headers()).get('x-fa-locale');
  const locale = isLocale(raw) ? raw : DEFAULT_LOCALE;
  const data = await loadShellData(locale);
  return (
    <I18nProvider locale={locale} messages={getMessages(locale)}>
      <ToastProvider>
        <AppShell data={data}>
          <NotFoundView t={createTranslator(locale)} locale={locale} signedIn={data.signedIn} />
        </AppShell>
      </ToastProvider>
    </I18nProvider>
  );
}
