import type { Metadata } from 'next';
import { Suspense } from 'react';
import type { Decision, FieldDetail } from '@fasalalert/shared/api';
import { Database, Plus } from '@/components/Icon';
import { EmptyState } from '@/components/Feedback/EmptyState';
import { RouteError } from '@/components/Feedback/RouteError';
import { RetryButton } from '@/components/Feedback/RetryButton';
import { Skeleton } from '@/components/Feedback/Skeleton';
import { PageMain, Section } from '@/components/Layout/Page';
import { RouteStrip } from '@/components/Map/RouteStrip';
import { ArrivalSparkline } from '@/components/Market/ArrivalSparkline';
import { MarketSelectors } from '@/components/Market/MarketSelectors';
import { PriceBand } from '@/components/Market/PriceBand';
import { RecommendationBand, type RecommendationVariant } from '@/components/Market/RecommendationBand';
import { PageHeader } from '@/components/Nav/PageHeader';
import { SourceLine } from '@/components/Risk/SourceLine';
import { ButtonLink } from '@/components/UI/Button';
import { Card } from '@/components/UI/Card';
import { Disclosure } from '@/components/UI/Disclosure';
import { getField, getFields, getHealth, getMandis, getMe, getPriceForecast, getPrices, getTransportRisk, redirectIfUnauthenticated } from '@/lib/api';
import { createTranslator } from '@/lib/i18n';
import { isLocale, type Locale } from '@/lib/locales';
import { isAbstention } from '@/lib/risk';
import { fromSourceRef, type ViewCtx } from '@/lib/view';
import styles from './market.module.css';

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  return { title: createTranslator(isLocale(locale) ? locale : 'mr')('market.title') };
}

type SP = Promise<Record<string, string | string[] | undefined>>;

async function PricePanels({ commodity, market, crop, days, summary, ctx, connected }: { commodity: string; market: string; crop: FieldDetail['crop']; days: 30 | 90; summary: Decision['market'] | null; ctx: ViewCtx; connected: boolean | null }) {
  const { t } = ctx;
  const [prices, forecast] = await Promise.all([getPrices(commodity, market, 90), getPriceForecast(commodity, market)]);
  if (!prices.ok && !summary) {
    return <Section id="price-h" title={t('market.price.title')}><RouteError message={t('state.sectionError', { section: t('section.price') })} action={<RetryButton />} /></Section>;
  }
  // No real prices: say why, and show no chart, no forecast and no zero values (docs/UX_QA_AUDIT.md MKT-01).
  if (prices.ok && prices.data.series.length === 0 && !summary) {
    return (
      <Section id="price-h" title={t('market.price.title')}>
        <div className={styles.unavailable} role="status">
          <h3 className={styles.unavailableTitle}><Database size={20} aria-hidden="true" /> {connected === false ? t('market.notConnected') : t('market.noPrices', { market })}</h3>
          <p>{connected === false ? t('market.notConnectedBody') : t('market.noPricesBody')}</p>
          <p className={styles.muted}>{t('market.noFabrication')}</p>
        </div>
      </Section>
    );
  }
  return (
    <>
      <Section id="price-h" title={t('market.price.title')}>
        <Card><PriceBand prices={prices.ok ? prices.data : null} forecast={forecast.ok ? forecast.data : null} summary={summary} crop={crop} days={days} ctx={ctx} /></Card>
      </Section>
      <Section id="arrivals-h" title={t('market.arrivals.title')}>
        <Card>{prices.ok && prices.data.series.length ? <ArrivalSparkline series={prices.data.series} market={market} ctx={ctx} /> : <p>{t('market.arrivals.none')}</p>}</Card>
      </Section>
    </>
  );
}

async function RoutePanel({ fieldId, ctx }: { fieldId: number; ctx: ViewCtx }) {
  const { t } = ctx;
  const tr = await getTransportRisk(fieldId);
  if (!tr.ok) return <Section id="route-h" title={t('market.route.title')}><RouteError message={t('market.route.unavailable')} /></Section>;
  if (!tr.data.available && tr.data.unavailable_reason === 'route_unknown') return null; // hidden (PRD §7.7)
  return (
    <Section id="route-h" title={t('market.route.title')}>
      <Card>
        {tr.data.available ? <RouteStrip risk={tr.data} ctx={ctx} headingId="route-h" /> : <p>{t('market.route.forecastStale')}</p>}
      </Card>
    </Section>
  );
}

/** R7 Market and transport for one field at a time (PRD §7.7, design.md 12.7). */
export default async function MarketPage({ params, searchParams }: { params: Promise<{ locale: string }>; searchParams: SP }) {
  const locale = (await params).locale as Locale;
  const sp = await searchParams;
  const t = createTranslator(locale);
  const now = new Date();
  const [fields, me] = await Promise.all([getFields(), getMe()]);
  await redirectIfUnauthenticated(fields, locale);
  const ctx: ViewCtx = { t, locale, now, unit: me.ok ? me.data.temp_unit : 'celsius' };
  const header = <PageHeader title={t('market.title')} description={t('market.description')} />;

  if (!fields.ok) {
    return <PageMain>{header}<RouteError variant="section" message={t('home.fieldsError')} action={<RetryButton />} /></PageMain>;
  }
  if (fields.data.length === 0) {
    return (
      <PageMain>
        {header}
        <EmptyState title={t('market.noFields')} action={<ButtonLink href={`/${locale}/onboarding`} icon={<Plus size={20} aria-hidden="true" />}>{t('nav.addField')}</ButtonLink>} />
      </PageMain>
    );
  }
  const wanted = typeof sp.field_id === 'string' ? Number(sp.field_id) : NaN;
  const field = fields.data.find((f) => f.id === wanted) ?? fields.data[0]!;
  const [detail, mandis, transport, health] = await Promise.all([getField(field.id), getMandis(field.district_id, field.crop, field.id), getTransportRisk(field.id), getHealth()]);
  const connected = health.ok ? health.data.integrations?.data_gov_in === 'configured' : null;
  const mandiList = mandis.ok ? [...mandis.data].sort((a, b) => (a.distance_km ?? Infinity) - (b.distance_km ?? Infinity)) : [];
  const wantedMandi = typeof sp.mandi === 'string' ? sp.mandi : null;
  const chosen = mandiList.find((m) => m.name === wantedMandi) ?? mandiList.find((m) => m.name === field.primary_mandi) ?? mandiList[0] ?? null;
  const decision = detail.ok && detail.data.last_decision && !isAbstention(detail.data.last_decision) ? detail.data.last_decision : null;
  const summary = decision?.market && (!chosen || decision.market.market === chosen.name) ? decision.market : null;
  const days: 30 | 90 = sp.range === '90' ? 90 : 30;
  const routeUnknown = transport.ok && !transport.data.available && transport.data.unavailable_reason === 'route_unknown';
  const transportFailed = !transport.ok;
  const maxP = transport.ok && transport.data.available ? Math.max(0, ...transport.data.days.map((d) => d.p_disruption)) : 0;
  const recVariant: RecommendationVariant = !decision?.recommendation ? 'unavailable' : routeUnknown || transportFailed ? 'price-only' : maxP >= 0.35 ? 'caution' : 'agree';
  const commodity = chosen?.commodity ?? field.crop;
  const key = `${field.id}-${chosen?.name ?? ''}-${days}`;

  return (
    <PageMain renderedAt={now.toISOString()}>
        {header}
        <MarketSelectors fields={fields.data.map((f) => ({ id: f.id, name: f.name, crop: f.crop }))} fieldId={field.id}
          mandis={mandiList.map((m) => ({ name: m.name, distance_km: m.distance_km }))} mandi={chosen?.name ?? null} />
        {!mandis.ok ? <RouteError message={t('market.mandisError')} action={<RetryButton />} /> : mandiList.length === 0 ? <p className={styles.muted}>{t('market.noMandis')}</p> : null}

        <RecommendationBand recommendation={decision?.recommendation ?? null} variant={recVariant} ctx={ctx} />

        <div className={styles.grid}>
          <div className={styles.priceCol}>
            {chosen ? (
              <Suspense key={key} fallback={<><Skeleton height={320} radius="md" /><Skeleton height={140} radius="md" /></>}>
                <PricePanels commodity={commodity} market={chosen.name} crop={field.crop} days={days} summary={summary} ctx={ctx} connected={connected} />
              </Suspense>
            ) : null}
          </div>
          <div className={styles.routeCol}>
            <Suspense key={`r-${field.id}`} fallback={<Skeleton height={220} radius="md" />}>
              <RoutePanel fieldId={field.id} ctx={ctx} />
            </Suspense>
          </div>
        </div>

        <Disclosure label={t('market.why')}>
          {decision?.sources?.length ? <SourceLine sources={decision.sources.map((s) => fromSourceRef(s))} t={t} locale={locale} now={now} /> : null}
          {transport.ok && transport.data.available ? <p className={styles.muted}>{transport.data.note}</p> : null}
          {decision?.market?.source ? <p className={styles.muted} lang="en">{decision.market.source}</p> : null}
        </Disclosure>
    </PageMain>
  );
}
