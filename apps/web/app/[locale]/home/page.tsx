import type { Metadata } from 'next';
import Link from 'next/link';
import { Suspense } from 'react';
import type { Abstention, Decision, Field, Risk } from '@fasalalert/shared/api';
import { ArrowRight, Bell, ChevronRight, CropIcon, IndianRupee, MapIcon, Mic, Plus, SlidersHorizontal, Sprout, Truck, Wheat } from '@/components/Icon';
import { EmptyState } from '@/components/Feedback/EmptyState';
import { RefreshWhilePending } from '@/components/Feedback/RefreshWhilePending';
import { RetryButton } from '@/components/Feedback/RetryButton';
import { RouteError } from '@/components/Feedback/RouteError';
import { LoadingRegion, Skeleton } from '@/components/Feedback/Skeleton';
import { FieldSwitcher } from '@/components/Home/FieldSwitcher';
import { OfflineSnapshot } from '@/components/Home/OfflineSnapshot';
import { PageMain, Section } from '@/components/Layout/Page';
import { PageHeader } from '@/components/Nav/PageHeader';
import { ActionWindow, DecisionCard, RiskBadge, TemperatureBand, WeatherSummary } from '@/components/Risk';
import { Banner } from '@/components/UI/Banner';
import { SampleTag } from '@/components/UI/Badges';
import { ButtonLink } from '@/components/UI/Button';
import { getActiveRisks, getAlerts, getDecisionsToday, getFields, getForecast, getMe, getTransportRisk, redirectIfUnauthenticated, type ApiResult } from '@/lib/api';
import { formatDateShort, formatDateTime, formatDayDate, formatRupees, istParts } from '@/lib/format';
import { createTranslator } from '@/lib/i18n';
import { isLocale, type Locale } from '@/lib/locales';
import { cardModel, isAbstention, isPinned, sortHome, topRisk } from '@/lib/risk';
import { kindLabel, loc, pctText, type ViewCtx } from '@/lib/view';
import styles from './home.module.css';

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  return { title: createTranslator(isLocale(locale) ? locale : 'mr')('home.title') };
}

type Decisions = ApiResult<(Decision | Abstention)[]>;
/** Stored decisions come back in milliseconds; a field's first decision can take 20 s or more to work out. */
const QUICK_MS = 1500;

function byFieldOf(decisions: Decisions): Map<number, Decision | Abstention> {
  return new Map((decisions.ok ? decisions.data : []).map((d) => [d.field_id, d]));
}

/**
 * Home (R3, docs/UX_QA_AUDIT.md HOME-01, HOME-02): "What should I know and do today?" One field at a time:
 * its decision and deadline first, then the week's weather; beside it, every field's status, unread alerts,
 * market and road outlook, and shortcuts. The page streams: the header, fields and alerts appear at once and
 * each slow section shows its own placeholder until its data arrives. Unavailable data is said to be
 * unavailable, never shown as zero.
 */
export default async function HomePage({ params, searchParams }: { params: Promise<{ locale: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const locale = (await params).locale as Locale;
  const sp = await searchParams;
  const t = createTranslator(locale);
  const now = new Date();
  const renderedAt = now.toISOString();
  const [me, fields, alerts] = await Promise.all([getMe(), getFields(), getAlerts()]);
  await redirectIfUnauthenticated(fields, locale);
  const unit = me.ok ? me.data.temp_unit : 'celsius';
  const ctx: ViewCtx = { t, locale, now, unit };
  const hour = istParts(now).hour;
  const part = hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening';
  const name = me.ok ? me.data.name : null;
  const greeting = t('home.greeting', { part, hasName: name ? 'yes' : 'no', name: name ?? '', date: formatDayDate(now, locale, now) });

  if (!fields.ok) {
    return (
      <PageMain renderedAt={renderedAt}>
        <PageHeader eyebrow={greeting} title={t('home.title')} />
        <RouteError variant="section" message={t('home.fieldsError')} code={fields.error?.trace_id} codeLabel={fields.error?.trace_id ? t('state.errorCode', { code: fields.error.trace_id }) : undefined} action={<RetryButton />} />
      </PageMain>
    );
  }

  if (fields.data.length === 0) {
    return (
      <PageMain renderedAt={renderedAt}>
        <PageHeader eyebrow={greeting} title={t('home.title')} />
        <EmptyState variant="page" icon={<Sprout size={48} aria-hidden="true" />} title={t('home.emptyTitle')} body={t('home.emptyFirst')}
          action={(
            <div className={styles.emptyActions}>
              <ButtonLink href={`/${locale}/onboarding`} size="lg" icon={<Plus size={20} aria-hidden="true" />}>{t('home.addFirst')}</ButtonLink>
              <ButtonLink href={`/${locale}/map`} variant="secondary" size="lg" icon={<MapIcon size={20} aria-hidden="true" />}>{t('home.seeOutlook')}</ButtonLink>
            </div>
          )} />
      </PageMain>
    );
  }

  // When decisions are already stored, show the most urgent field first; otherwise do not wait for them.
  const quick = await Promise.race([getDecisionsToday(), new Promise<null>((r) => setTimeout(() => r(null), QUICK_MS))]);
  const ordered = quick
    ? sortHome(fields.data.map((f) => ({ fieldId: f.id, fieldName: f.name, decision: byFieldOf(quick).get(f.id) ?? null, field: f })), now).map((o) => o.field)
    : fields.data;
  const wanted = typeof sp.field === 'string' ? Number(sp.field) : NaN;
  const field = fields.data.find((f) => f.id === wanted) ?? ordered[0]!;
  const unreadAlerts = alerts.ok ? alerts.data.alerts.filter((a) => !a.read_at).slice(0, 3) : [];
  const unreadCount = alerts.ok ? alerts.data.unread : 0;
  const panel = (h: number) => <div className={styles.panel}><Skeleton height={20} width="50%" /><Skeleton height={h} radius="md" /></div>;

  return (
    <PageMain renderedAt={renderedAt}>
      <PageHeader
        eyebrow={greeting}
        title={t('home.title')}
        description={[field.name, loc(field.location_label, locale)].filter(Boolean).join(' · ')}
        actions={fields.data.length > 1 ? <FieldSwitcher fields={ordered.map((f) => ({ id: f.id, name: f.name }))} value={field.id} /> : undefined}
      />

      <div className={styles.dashboard}>
        <div className={styles.primary}>
          <section aria-labelledby="today-h" className={styles.today}>
            <h2 id="today-h" className={styles.sectionTitle}>{t('home.todayDecision')}</h2>
            <Suspense fallback={(
              <LoadingRegion label={t('home.working', { field: field.name })} className={styles.working}>
                <p className={styles.workingText} aria-hidden="true">{t('home.working', { field: field.name })}</p>
                <Skeleton height={180} radius="md" />
              </LoadingRegion>
            )}>
              <TodayDecision field={field} ctx={ctx} renderedAt={renderedAt} />
            </Suspense>
            <Link href={`/${locale}/field/${field.id}`} className={styles.more}>{t('home.whyLink')}<ArrowRight size={18} aria-hidden="true" /></Link>
          </section>

          <Section id="wx-h" title={t('home.weather')}>
            <Suspense fallback={panel(120)}><Weather field={field} ctx={ctx} /></Suspense>
          </Section>
        </div>

        <aside className={styles.side} aria-label={t('home.overview')}>
          <section className={styles.panel} aria-labelledby="fields-h">
            <div className={styles.panelHead}>
              <h2 id="fields-h" className={styles.panelTitle}><Wheat size={20} aria-hidden="true" /> {t('home.yourFields', { count: fields.data.length })}</h2>
              <Link href={`/${locale}/fields`} className={styles.panelLink}>{t('home.allFields')}</Link>
            </div>
            <Suspense fallback={<FieldRows fields={ordered} selected={field.id} decisions={null} ctx={ctx} />}>
              <FieldRowsLive fields={ordered} selected={field.id} ctx={ctx} />
            </Suspense>
            {fields.data.length > 5 ? <Link href={`/${locale}/fields`} className={styles.panelLink}>{t('nav.allFields', { count: fields.data.length })}</Link> : null}
            <ButtonLink href={`/${locale}/fields/new`} variant="secondary" icon={<Plus size={20} aria-hidden="true" />}>{t('nav.addField')}</ButtonLink>
          </section>

          <section className={styles.panel} aria-labelledby="alerts-h">
            <div className={styles.panelHead}>
              <h2 id="alerts-h" className={styles.panelTitle}><Bell size={20} aria-hidden="true" /> {t('home.alerts')}</h2>
              <Link href={`/${locale}/alert`} className={styles.panelLink}>{unreadCount ? t('alerts.unread', { count: unreadCount }) : t('home.allAlerts')}</Link>
            </div>
            {!alerts.ok ? <p className={styles.muted}>{t('alerts.loadError')}</p> : unreadAlerts.length === 0 ? <p className={styles.muted}>{t('home.noUnread')}</p> : (
              <ul className={styles.alertList}>
                {unreadAlerts.map((a) => (
                  <li key={a.id}>
                    <Link href={`/${locale}/alert?focus=${a.id}`} className={styles.alertRow}>
                      <RiskBadge level={a.level} kind={a.kind === 'price' ? undefined : a.kind} size="sm" t={t} />
                      <span className={styles.alertText}>
                        <span>{kindLabel(t, a.kind)}{a.field_name ? ` · ${a.field_name}` : ''}</span>
                        <span className={styles.muted}>{formatDateTime(a.sent_at ?? a.created_at, locale, now)}</span>
                      </span>
                      <ChevronRight size={18} aria-hidden="true" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <Suspense fallback={panel(60)}><MarketPanel field={field} ctx={ctx} /></Suspense>
          <Suspense fallback={panel(60)}><RoadPanel field={field} ctx={ctx} /></Suspense>

          <section className={styles.panel} aria-labelledby="quick-h">
            <h2 id="quick-h" className={styles.panelTitle}>{t('home.quick')}</h2>
            <ul className={styles.quick}>
              <li><Link href={`/${locale}/ask?field_id=${field.id}`}><Mic size={20} aria-hidden="true" />{t('home.quickAsk')}</Link></li>
              <li><Link href={`/${locale}/map`}><MapIcon size={20} aria-hidden="true" />{t('nav.map')}</Link></li>
              <li><Link href={`/${locale}/settings/calibration?field_id=${field.id}`}><SlidersHorizontal size={20} aria-hidden="true" />{t('nav.calibration')}</Link></li>
            </ul>
          </section>
        </aside>
      </div>

      <Suspense fallback={null}><Snapshot fields={fields.data} renderedAt={renderedAt} kvk={me.ok ? me.data.district_kvk : null} /></Suspense>
    </PageMain>
  );
}

async function TodayDecision({ field, ctx, renderedAt }: { field: Field; ctx: ViewCtx; renderedAt: string }) {
  const { t, locale, now } = ctx;
  const decisions = await getDecisionsToday();
  const decision = byFieldOf(decisions).get(field.id) ?? null;
  // Decision engine down: show the raw model outputs without a recommendation (PRD §7.3).
  const engineDown = !decisions.ok && decisions.kind === 'http' && decisions.status >= 500 && decisions.error?.code !== 'data_stale';
  const allStale = !decisions.ok && decisions.error?.code === 'data_stale';
  if (!decisions.ok && decisions.kind === 'network') return <RouteError variant="section" message={t('home.loadError')} action={<RetryButton />} />;
  const raw = engineDown ? await getActiveRisks(field.id) : null;
  const rawRisks: Risk[] | undefined = raw && raw.ok ? raw.data : undefined;
  const staleAt = allStale && !decisions.ok ? String(decisions.error?.details?.last_update ?? '') || null : null;
  const stageLabel = field.stage?.stage_label ? loc(field.stage.stage_label, locale) : null;
  const d = decision && !isAbstention(decision) ? decision : null;
  const drive = d ? topRisk(d.risks) : null;
  const extra = d && drive && (drive.kind === 'frost' || drive.kind === 'heatwave') && drive.level !== 'none' ? (
    <div className={styles.extra}>
      {typeof drive.tmin_c === 'number' && drive.window_start ? (
        <TemperatureBand kind={drive.kind === 'frost' ? 'frost' : 'heat'} series={[]} event={{ at: drive.window_start, valueC: drive.tmin_c, lowC: drive.band_low_c ?? null, highC: drive.band_high_c ?? null }}
          thresholdC={drive.threshold_c ?? null} thresholdLabel={stageLabel ? t('tband.stageThreshold', { stage: stageLabel }) : t('tband.thresholdDefault')} level={drive.level} sources={[]} compact ctx={ctx} />
      ) : null}
      <ActionWindow actionBy={d.action_by} windowStart={drive.window_start} windowEnd={drive.window_end} kind={drive.kind} level={drive.level} compact t={t} locale={locale} now={now} />
    </div>
  ) : null;
  return (
    <>
      {engineDown ? <Banner variant="warning">{t('state.engineDown.banner')}</Banner> : null}
      <DecisionCard
        headingLevel={3}
        variant="full"
        field={{ id: field.id, name: field.name, crop: field.crop, variety: field.variety, stageLabel }}
        decision={allStale ? null : decision}
        state={engineDown ? 'raw' : undefined}
        rawRisks={rawRisks}
        pinned={isPinned(decision, now)}
        ctx={ctx}
        href={`/${locale}/field/${field.id}`}
        renderedAt={renderedAt}
        staleSince={staleAt}
        extra={extra}
        abstainAction={decision && decision.abstain_reason === 'missing_field_input'
          ? <ButtonLink href={`/${locale}/field/${field.id}?edit=sowing`} variant="primary">{t('abstain.missing_field_input.action')}</ButtonLink>
          : undefined}
      />
      {!decision && !engineDown && !allStale ? <><p className={styles.muted}>{t('home.decisionPending')}</p><RefreshWhilePending /></> : null}
    </>
  );
}

async function Weather({ field, ctx }: { field: Field; ctx: ViewCtx }) {
  const { t, locale, now } = ctx;
  const forecast = await getForecast(field.id);
  return (
    <div className={styles.panel}>
      {forecast.ok && forecast.data.rows.length ? <WeatherSummary forecast={forecast.data} fieldName={field.name} ctx={ctx} /> : <p className={styles.muted}>{t('wx.unavailable')}</p>}
      {forecast.ok && forecast.data.stale ? <p className={styles.staleNote}>{t('state.stale.card', { time: formatDateTime(forecast.data.source.fetched_at, locale, now) })}</p> : null}
    </div>
  );
}

async function FieldRowsLive({ fields, selected, ctx }: { fields: Field[]; selected: number; ctx: ViewCtx }) {
  return <FieldRows fields={fields} selected={selected} decisions={byFieldOf(await getDecisionsToday())} ctx={ctx} />;
}

function FieldRows({ fields, selected, decisions, ctx }: { fields: Field[]; selected: number; decisions: Map<number, Decision | Abstention> | null; ctx: ViewCtx }) {
  const { t, locale, now } = ctx;
  return (
    <ul className={styles.fieldList}>
      {fields.slice(0, 5).map((f) => {
        const fd = decisions?.get(f.id) ?? null;
        return (
          <li key={f.id}>
            <Link href={`/${locale}/home?field=${f.id}`} className={styles.fieldRow} aria-current={f.id === selected ? 'true' : undefined} scroll={false}>
              <CropIcon crop={f.crop} size={24} />
              <span className={styles.fieldName}>{f.name}</span>
              {decisions === null ? <Skeleton height={22} width={64} radius="full" />
                : fd && !isAbstention(fd) ? <RiskBadge level={cardModel(fd, now).level} size="sm" t={t} />
                  : <span className={styles.muted}>{fd ? t('home.needsAttention') : t('home.noDecisionYet')}</span>}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

async function MarketPanel({ field, ctx }: { field: Field; ctx: ViewCtx }) {
  const { t, locale, now } = ctx;
  const decision = byFieldOf(await getDecisionsToday()).get(field.id) ?? null;
  const market = decision && !isAbstention(decision) ? decision.market : null;
  return (
    <section className={styles.panel} aria-labelledby="market-h">
      <div className={styles.panelHead}>
        <h2 id="market-h" className={styles.panelTitle}><IndianRupee size={20} aria-hidden="true" /> {t('home.market')}</h2>
        <Link href={`/${locale}/market?field_id=${field.id}`} className={styles.panelLink}>{t('home.openMarket')}</Link>
      </div>
      {market ? (
        <div className={styles.stack}>
          <p className={styles.big}>{formatRupees(market.modal_rs_qtl, locale)}<span className={styles.unit}> / {t('units.qtl')}</span></p>
          <p className={styles.muted}>{t('home.marketLine', { market: market.market, date: market.price_date ? formatDateShort(market.price_date, locale, now) : '' })}</p>
          {market.source === 'synthetic_seed' ? <SampleTag label={t('common.sampleData')} /> : null}
        </div>
      ) : <p className={styles.muted}>{t('home.marketUnavailable')}</p>}
    </section>
  );
}

async function RoadPanel({ field, ctx }: { field: Field; ctx: ViewCtx }) {
  const { t, locale, now } = ctx;
  const transport = await getTransportRisk(field.id);
  const tr = transport.ok ? transport.data : null;
  const next = tr && tr.available ? tr.days.slice(0, 3) : [];
  const top = next.length ? next.reduce((a, b) => (b.p_disruption > a.p_disruption ? b : a)) : null;
  return (
    <section className={styles.panel} aria-labelledby="road-h">
      <div className={styles.panelHead}>
        <h2 id="road-h" className={styles.panelTitle}><Truck size={20} aria-hidden="true" /> {t('home.road')}</h2>
      </div>
      {tr && tr.available && top ? (
        <div className={styles.stack}>
          <div className={styles.inline}><RiskBadge level={top.level} kind="transport" size="sm" t={t} /><span>{pctText(t, top.p_disruption, locale)}</span></div>
          <p className={styles.muted}>{t('home.roadLine', { route: tr.route_name ?? '', date: formatDateShort(top.date, locale, now) })}</p>
          <p className={styles.note}>{t('home.roadNote')}</p>
        </div>
      ) : <p className={styles.muted}>{tr?.unavailable_reason === 'forecast_stale' ? t('market.route.forecastStale') : tr?.unavailable_reason === 'route_unknown' ? t('home.roadUnknown') : t('market.route.unavailable')}</p>}
    </section>
  );
}

async function Snapshot({ fields, renderedAt, kvk }: { fields: Field[]; renderedAt: string; kvk: { name: string; phone: string } | null }) {
  const decisions = await getDecisionsToday();
  return (
    <OfflineSnapshot snapshot={{
      savedAt: renderedAt,
      fields: fields.map((f) => ({ id: f.id, name: f.name, crop: f.crop, variety: f.variety })),
      decisions: decisions.ok ? decisions.data : [],
      kvk,
    }} />
  );
}
