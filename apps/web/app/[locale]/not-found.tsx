import { headers } from 'next/headers';
import { NotFoundView } from '@/components/System/NotFoundView';
import { hasSession } from '@/lib/api';
import { createTranslator } from '@/lib/i18n';
import { DEFAULT_LOCALE, isLocale } from '@/lib/locales';

/** R12 Not found inside the locale layout: AppShell when signed in, SystemShell otherwise. */
export default async function LocaleNotFound() {
  const raw = (await headers()).get('x-fa-locale');
  const locale = isLocale(raw) ? raw : DEFAULT_LOCALE;
  return <NotFoundView t={createTranslator(locale)} locale={locale} signedIn={await hasSession()} />;
}
