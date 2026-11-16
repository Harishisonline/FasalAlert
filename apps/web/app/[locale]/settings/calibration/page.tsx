import type { Metadata } from 'next';
import { Plus } from '@/components/Icon';
import { EmptyState } from '@/components/Feedback/EmptyState';
import { RouteError } from '@/components/Feedback/RouteError';
import { RetryButton } from '@/components/Feedback/RetryButton';
import { PageMain } from '@/components/Layout/Page';
import { PageHeader } from '@/components/Nav/PageHeader';
import { CalibrationForm } from '@/components/Settings/CalibrationForm';
import { CalibrationGuide } from '@/components/Settings/CalibrationGuide';
import { ButtonLink } from '@/components/UI/Button';
import { getCalibration, getFields, getMandis, redirectIfUnauthenticated } from '@/lib/api';
import { createTranslator } from '@/lib/i18n';
import { isLocale, type Locale } from '@/lib/locales';

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  return { title: createTranslator(isLocale(locale) ? locale : 'mr')('calib.title') };
}

/** R9b Calibration (PRD §7.10, design.md 12.10). */
export default async function CalibrationPage({ params, searchParams }: { params: Promise<{ locale: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const locale = (await params).locale as Locale;
  const sp = await searchParams;
  const t = createTranslator(locale);
  const fields = await getFields();
  await redirectIfUnauthenticated(fields, locale);
  const header = <PageHeader back={{ href: `/${locale}/settings`, label: t('calib.backSettings') }} title={t('calib.title')} description={t('calib.description')} />;
  if (!fields.ok) return <PageMain width="reading">{header}<RouteError variant="section" message={t('home.fieldsError')} action={<RetryButton />} /></PageMain>;
  if (fields.data.length === 0) {
    return (
      <PageMain width="reading">
        {header}
        <EmptyState title={t('calib.noFields')} action={<ButtonLink href={`/${locale}/onboarding`} icon={<Plus size={20} aria-hidden="true" />}>{t('nav.addField')}</ButtonLink>} />
      </PageMain>
    );
  }
  const wanted = typeof sp.field_id === 'string' ? Number(sp.field_id) : NaN;
  const field = fields.data.find((f) => f.id === wanted) ?? fields.data[0]!;
  const [cal, mandis] = await Promise.all([getCalibration(field.id), getMandis(field.district_id, field.crop, field.id)]);
  return (
    <PageMain width="reading">
        {header}
        <CalibrationGuide t={t} />
        {cal.ok ? (
          <CalibrationForm key={field.id} fields={fields.data.map((f) => ({ id: f.id, name: f.name, crop: f.crop }))} fieldId={field.id} crop={field.crop}
            calibration={cal.data} primaryMandi={field.primary_mandi}
            mandis={mandis.ok ? [...mandis.data].sort((a, b) => (a.distance_km ?? Infinity) - (b.distance_km ?? Infinity)).map((m) => ({ name: m.name, distance_km: m.distance_km })) : []} />
        ) : (
          <RouteError variant="section" message={t('calib.loadError')} code={cal.error?.trace_id} codeLabel={cal.error?.trace_id ? t('state.errorCode', { code: cal.error.trace_id }) : undefined} action={<RetryButton />} />
        )}
    </PageMain>
  );
}
