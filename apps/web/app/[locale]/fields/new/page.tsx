import type { Metadata } from 'next';
import { OnboardingWizard } from '@/components/Onboarding/OnboardingWizard';
import { getDistricts, getFields, getMe, redirectIfUnauthenticated } from '@/lib/api';
import { loadCropTable } from '@/lib/crops';
import { createTranslator } from '@/lib/i18n';
import { isLocale, type Locale } from '@/lib/locales';

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  return { title: createTranslator(isLocale(locale) ? locale : 'mr')('onb.addTitle') };
}

/** Add another field: the same wizard as first-time onboarding, returning to My Fields when saved. */
export default async function AddFieldPage({ params }: { params: Promise<{ locale: string }> }) {
  const locale = (await params).locale as Locale;
  const [me, districts, fields, crops] = await Promise.all([getMe(), getDistricts(), getFields(), loadCropTable()]);
  await redirectIfUnauthenticated(me, locale);
  const count = fields.ok ? fields.data.length : 0;
  return (
    <OnboardingWizard mode={count > 0 ? 'add' : 'first'} districts={districts.ok ? districts.data : []} districtsFailed={!districts.ok}
      fieldCount={count} areaUnit={me.ok ? me.data.area_unit : 'hectare'} crops={crops} />
  );
}
