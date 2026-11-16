import type { Metadata } from 'next';
import { cookies } from 'next/headers';
import { RouteError } from '@/components/Feedback/RouteError';
import { RetryButton } from '@/components/Feedback/RetryButton';
import { PageMain } from '@/components/Layout/Page';
import { PageHeader } from '@/components/Nav/PageHeader';
import { SettingsForm } from '@/components/Settings/SettingsForm';
import { getMe, redirectIfUnauthenticated } from '@/lib/api';
import { createTranslator } from '@/lib/i18n';
import { THEME_COOKIE, isLocale, parseTheme, type Locale } from '@/lib/locales';

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  return { title: createTranslator(isLocale(locale) ? locale : 'mr')('settings.title') };
}

/** R9a Settings (PRD §7.9, design.md 12.9). */
export default async function SettingsPage({ params }: { params: Promise<{ locale: string }> }) {
  const locale = (await params).locale as Locale;
  const t = createTranslator(locale);
  const me = await getMe();
  await redirectIfUnauthenticated(me, locale);
  const theme = parseTheme((await cookies()).get(THEME_COOKIE)?.value);
  return (
    <PageMain width="reading">
      <PageHeader title={t('settings.title')} description={t('settings.description')} />
      {me.ok ? <SettingsForm me={me.data} theme={theme} /> : (
        <RouteError variant="section" message={t('settings.loadError')} code={me.error?.trace_id} codeLabel={me.error?.trace_id ? t('state.errorCode', { code: me.error.trace_id }) : undefined} action={<RetryButton />} />
      )}
    </PageMain>
  );
}
