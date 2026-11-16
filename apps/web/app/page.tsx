import type { Metadata } from 'next';
import { headers } from 'next/headers';
import { I18nProvider } from '@/components/I18n';
import { Landing } from '@/components/Landing/Landing';
import { StaticDistrictMap } from '@/components/Map/StaticDistrictMap';
import { PublicHeader } from '@/components/Nav/PublicHeader';
import { SkipLink } from '@/components/UI/SkipLink';
import { ToastProvider } from '@/components/UI/Toast';
import { formatTime } from '@/lib/format';
import { loadDistrictGeo, toSvg } from '@/lib/geo';
import { createTranslator, getMessages } from '@/lib/i18n';
import { DEFAULT_LOCALE, isLocale } from '@/lib/locales';
import { getBoard } from '@/lib/public-cache';
import { FORECAST_STALE_MS, isOlderThan, type DisplayLevel } from '@/lib/risk';

async function pageLocale() {
  const raw = (await headers()).get('x-fa-locale');
  return isLocale(raw) ? raw : DEFAULT_LOCALE;
}

export async function generateMetadata(): Promise<Metadata> {
  const t = createTranslator(await pageLocale());
  return { title: { absolute: `FasalAlert · ${t('landing.metaTitle')}` }, description: t('meta.description') };
}

/**
 * The landing page (docs/UX_QA_AUDIT.md FLOW-01). Language from ?lang=, the NEXT_LOCALE cookie or
 * Accept-Language (proxy.ts). The regional outlook preview is the live public board drawn as a static map;
 * the interactive map is at /[locale]/map.
 */
export default async function LandingPage() {
  const locale = await pageLocale();
  const t = createTranslator(locale);
  const [board, geo] = await Promise.all([getBoard(), loadDistrictGeo()]);
  const svg = geo ? toSvg(geo) : null;
  const districts = board.kind === 'down' ? [] : board.data.districts;
  const levels: Record<string, DisplayLevel> = Object.fromEntries(districts.map((d) => [d.code, d.level]));
  const now = new Date();
  const generatedAt = board.kind === 'down' ? null : board.data.generated_at;
  const live = board.kind === 'live' && !board.data.stale && !isOlderThan(generatedAt, FORECAST_STALE_MS, now);
  return (
    <I18nProvider locale={locale} messages={getMessages(locale)}>
      <ToastProvider>
        <SkipLink href="#main">{t('skip.main')}</SkipLink>
        <PublicHeader languageMode="query"
          links={[
            { href: '#features', label: t('landing.nav.features'), key: 'features' },
            { href: '#how', label: t('landing.nav.how'), key: 'how' },
            { href: '#trust', label: t('landing.nav.trust'), key: 'trust' },
            { href: '#about', label: t('landing.nav.about'), key: 'about' },
          ]} />
        <Landing t={t} locale={locale}
          board={board.kind === 'down' ? null : { districts, generatedAt, live, timeIst: generatedAt ? formatTime(generatedAt, locale) : null }}
          preview={svg ? <StaticDistrictMap map={svg} levels={levels} label={t('landing.outlook.mapLabel')} /> : null} />
      </ToastProvider>
    </I18nProvider>
  );
}
