import type { Metadata } from 'next';
import { PageMain } from '@/components/Layout/Page';
import { FocusHeader } from '@/components/Nav/FocusHeader';
import { OfflineView } from '@/components/System/OfflineView';
import { createTranslator } from '@/lib/i18n';
import { isLocale, type Locale } from '@/lib/locales';

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  return { title: createTranslator(isLocale(locale) ? locale : 'mr')('meta.offlineTitle') };
}

/** R10 Offline: the PWA document fallback, precached per locale (design.md 20.5). SystemShell. */
export default async function OfflinePage({ params }: { params: Promise<{ locale: string }> }) {
  const locale = (await params).locale as Locale;
  const t = createTranslator(locale);
  return (
    <>
      <FocusHeader home={`/${locale}/home`} label={t('nav.homeBrand')} />
      <PageMain width="reading">
        <OfflineView />
      </PageMain>
    </>
  );
}
