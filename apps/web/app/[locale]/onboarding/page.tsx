import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { OnboardingWizard } from '@/components/Onboarding/OnboardingWizard';
import { getDistricts, getFields, getMe, redirectIfUnauthenticated } from '@/lib/api';
import { loadCropTable } from '@/lib/crops';
import { createTranslator } from '@/lib/i18n';
import { isLocale, type Locale } from '@/lib/locales';

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  return { title: createTranslator(isLocale(locale) ? locale : 'mr')('onb.title') };
}

/**
 * First-time onboarding (R8) in a focused layout. A user who already has a field is never sent through
 * first-time setup again (docs/UX_QA_AUDIT.md FLOW-03): they go to Add field instead.
 */
export default async function OnboardingPage({ params }: { params: Promise<{ locale: string }> }) {
  const locale = (await params).locale as Locale;
  const [me, districts, fields, crops] = await Promise.all([getMe(), getDistricts(), getFields(), loadCropTable()]);
  await redirectIfUnauthenticated(me, locale);
  if (fields.ok && fields.data.length > 0) redirect(`/${locale}/fields/new`);
  return (
    <OnboardingWizard mode="first" districts={districts.ok ? districts.data : []} districtsFailed={!districts.ok}
      fieldCount={0} areaUnit={me.ok ? me.data.area_unit : 'hectare'} crops={crops} />
  );
}
