import type { Metadata } from 'next';
import { RegionalOutlook } from '@/components/Board/RegionalOutlook';
import { StaticDistrictMap } from '@/components/Map/StaticDistrictMap';
import { GEO_URL, loadDistrictGeo, toSvg } from '@/lib/geo';
import { createTranslator } from '@/lib/i18n';
import { isLocale, type Locale } from '@/lib/locales';
import { getBoard } from '@/lib/public-cache';
import type { DisplayLevel } from '@/lib/risk';

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  const t = createTranslator(isLocale(locale) ? locale : 'mr');
  return { title: t('map.title'), description: t('map.description') };
}

/**
 * Regional outlook (formerly R1 at `/`, PRD §7.1 content unchanged): district frost and heat risk for all 36
 * districts. Public, so a farmer can look before signing in; inside the app shell when signed in. The title,
 * stamp and list are server-rendered so they show before WebGL starts.
 */
export default async function RegionalOutlookPage({ params, searchParams }: { params: Promise<{ locale: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const locale = (await params).locale as Locale;
  const t = createTranslator(locale);
  const sp = await searchParams;
  const [board, geo] = await Promise.all([getBoard(), loadDistrictGeo()]);
  const svg = geo ? toSvg(geo) : null;
  const districts = board.kind === 'down' ? [] : board.data.districts;
  const levels: Record<string, DisplayLevel> = Object.fromEntries(districts.map((d) => [d.code, d.level]));
  const district = typeof sp.district === 'string' && districts.some((d) => d.code === sp.district) ? sp.district : null;
  return (
    <RegionalOutlook
      mode={board.kind}
      generatedAt={board.kind === 'down' ? null : board.data.generated_at}
      stale={board.kind === 'down' ? false : Boolean(board.data.stale)}
      districts={districts}
      sources={board.kind === 'down' ? [] : board.data.sources ?? []}
      geoAvailable={Boolean(svg)}
      geoUrl={GEO_URL}
      bbox={geo?.bbox ?? null}
      skeleton={svg ? <StaticDistrictMap map={svg} pulse /> : null}
      fallback={svg ? <StaticDistrictMap map={svg} levels={levels} selected={district} label={t('board.mapLabel')} /> : null}
      initialDistrict={district}
      renderedAt={new Date().toISOString()}
    />
  );
}
