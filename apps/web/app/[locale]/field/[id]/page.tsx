import type { Metadata } from 'next';
import { Suspense } from 'react';
import { notFound } from 'next/navigation';
import type { Abstention, Decision, DecisionHistoryItem, ForecastResponse, Risk, TransportRiskResponse } from '@fasalalert/shared/api';
import { CheckCheck, CircleCheck, CircleMinus, Clock, CropIcon, KindIcon, Mic, Ruler } from '@/components/Icon';
import { RouteError } from '@/components/Feedback/RouteError';
import { Skeleton } from '@/components/Feedback/Skeleton';
import { RefreshWhilePending } from '@/components/Feedback/RefreshWhilePending';
import { RetryButton } from '@/components/Feedback/RetryButton';
import { FeedbackButton } from '@/components/Field/FeedbackButton';
import { FieldEditor } from '@/components/Field/FieldEditor';
import { PageMain, Section } from '@/components/Layout/Page';
import { RouteStrip } from '@/components/Map/RouteStrip';
import { PriceBand } from '@/components/Market/PriceBand';
import { RecommendationBand, type RecommendationVariant } from '@/components/Market/RecommendationBand';
import { PageHeader } from '@/components/Nav/PageHeader';
import { ActionWindow, DecisionCard, ProbabilityMeter, RiskBadge, SourceLine, StageTimeline, TemperatureBand, WeatherSummary } from '@/components/Risk';
import { Banner } from '@/components/UI/Banner';
import { ButtonLink } from '@/components/UI/Button';
import { Card } from '@/components/UI/Card';
import { Disclosure } from '@/components/UI/Disclosure';
import { getFieldHistory, getField, getForecast, getActiveRisks, getMe, getTransportRisk, redirectIfUnauthenticated } from '@/lib/api';
import { loadCropTable, varietyLabel } from '@/lib/crops';
import { areaFromSqm, formatDateShort, formatDateTime, formatNumber, formatTemp, formatTime, formatWithUnit } from '@/lib/format';
import { createTranslator } from '@/lib/i18n';
import { isLocale, type Locale } from '@/lib/locales';
import { compareLevel, isAbstention, topRisk } from '@/lib/risk';
import { cropLabel, fromSourceRef, kindLabel, levelLabel, loc, pctText, type ViewCtx } from '@/lib/view';
import styles from './field.module.css';

type Params = { params: Promise<{ locale: string; id: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { locale, id } = await params;
  const f = /^\d+$/.test(id) ? await getField(Number(id)) : null;
  return { title: f?.ok ? f.data.name : createTranslator(isLocale(locale) ? locale : 'mr')('field.decision') };
}

const EVIDENCE_KEYS = ['forecast_source', 'forecast_fetched_at', 'forecast_rain_mm', 'ensemble_members', 'rule', 'station', 'station_distance_km', 'field_elevation_m', 'gdd_cum', 'stage', 'method'];

function forecastSeries(fc: ForecastResponse | null, kind: 'frost' | 'heat') {
  if (!fc) return [];
  return fc.rows
    .map((r) => ({ at: `${r.valid_date}T12:00:00+05:30`, valueC: (kind === 'frost' ? r.tmin_c : r.tmax_c) as number, observed: false }))
    .filter((p) => typeof p.valueC === 'number');
}

/** R4 Field detail: the why behind the Home card (PRD §7.4, design.md 12.4). */
export default async function FieldDetailPage({ params, searchParams }: Params) {
  const { locale: rawLocale, id } = await params;
  const locale = rawLocale as Locale;
  if (!/^\d+$/.test(id)) notFound();
  const fieldId = Number(id);
  const sp = await searchParams;
  const t = createTranslator(locale);
  const now = new Date();
  const renderedAt = now.toISOString();
  // Transport streams in its own section: a new field's first route lookup can take tens of seconds (HOME-02).
  const [fieldRes, me, history, forecast, active, crops] = await Promise.all([
    getField(fieldId), getMe(), getFieldHistory(fieldId), getForecast(fieldId), getActiveRisks(fieldId), loadCropTable(),
  ]);
  await redirectIfUnauthenticated(fieldRes, locale);
  // Another user's field is a 404, never a 403 (PRD §7.4).
  if (!fieldRes.ok && (fieldRes.status === 404 || fieldRes.status === 403)) notFound();
  const unit = me.ok ? me.data.temp_unit : 'celsius';
  const ctx: ViewCtx = { t, locale, now, unit };
  const back = { href: `/${locale}/fields`, label: t('field.backToFields') };

  if (!fieldRes.ok) {
    return (
      <>
        <PageMain renderedAt={renderedAt}>
          <PageHeader back={back} title={t('field.decision')} />
          <RouteError variant="section" message={t('state.sectionError', { section: t('section.decision') })}
            code={fieldRes.error?.trace_id} codeLabel={fieldRes.error?.trace_id ? t('state.errorCode', { code: fieldRes.error.trace_id }) : undefined} action={<RetryButton />} />
        </PageMain>
      </>
    );
  }

  const field = fieldRes.data;
  const decision = field.last_decision as Decision | Abstention | null;
  const d = decision && !isAbstention(decision) ? decision : null;
  const risks: Risk[] = (active.ok ? active.data : field.risks ?? []).slice().sort((a, b) => compareLevel(b.level, a.level));
  const drive = d ? topRisk(d.risks) : null;
  const stageLabel = field.stage?.stage_label ? loc(field.stage.stage_label, locale) : null;
  const fc = forecast.ok ? forecast.data : null;
  const routeKnown = Boolean(d?.transport);
  const areaUnit = me.ok ? me.data.area_unit : 'hectare';
  const varieties = Object.fromEntries(Object.entries(crops).map(([k, v]) => [k, v.varieties])) as Record<string, { key: string; name: { en: string; mr: string; hi: string } }[]>;

  const meta = (
    <p className={styles.meta}>
      <CropIcon crop={field.crop} size={24} />
      <span>{[cropLabel(t, field.crop), varietyLabel(crops, field.crop, field.variety, locale), stageLabel ?? t('field.stage.unknownShort'), loc(field.location_label, locale)].filter(Boolean).join(' · ')}</span>
      {field.area_sqm ? <span className={styles.area}><Ruler size={16} aria-hidden="true" /> {formatWithUnit(areaFromSqm(field.area_sqm, areaUnit), areaUnit === 'acre' ? t('units.acre') : t('units.ha'), locale, 1)}</span> : null}
    </p>
  );

  // Risk evidence carries the internal stage key ("ripening_harvest"); readers see the stage's name (UX_QA_AUDIT FD-02).
  const thresholdLabel = stageLabel ? t('tband.stageThreshold', { stage: stageLabel }) : t('tband.thresholdDefault');

  const eventOf = (r: Risk) => (typeof r.tmin_c === 'number' && r.window_start
    ? { at: r.window_start, valueC: r.tmin_c, lowC: r.band_low_c ?? null, highC: r.band_high_c ?? null } : null);

  const riskSources = (r: Risk) => [
    ...(r.evidence?.forecast_source ? [{ label: String(r.evidence.forecast_source), at: r.evidence.forecast_fetched_at ?? null, kind: 'forecast' as const }] : []),
    { label: r.model_version, kind: 'model' as const, at: null },
  ];

  const decisionExtra = d && drive && (drive.kind === 'frost' || drive.kind === 'heatwave') ? (
    <div className={styles.extra}>
      {eventOf(drive) ? (
        <TemperatureBand kind={drive.kind === 'frost' ? 'frost' : 'heat'} series={[]} event={eventOf(drive)} thresholdC={drive.threshold_c ?? null}
          thresholdLabel={thresholdLabel} level={drive.level} sources={[]} compact ctx={ctx} />
      ) : null}
      <ActionWindow actionBy={d.action_by} windowStart={drive.window_start} windowEnd={drive.window_end} kind={drive.kind} level={drive.level} compact t={t} locale={locale} now={now} />
    </div>
  ) : null;

  const recVariant: RecommendationVariant = !d?.recommendation ? 'unavailable' : !routeKnown ? 'price-only'
    : d.transport && d.transport.p_disruption_72h >= 0.35 ? 'caution' : 'agree';

  const historyItems: DecisionHistoryItem[] = history.ok ? history.data : [];
  const hadRisk = historyItems.some((h) => h.alerts.length > 0 || (!isAbstention(h.decision) && h.decision.risks.some((r) => r.level !== 'none')));

  return (
    <>
      <PageMain renderedAt={renderedAt}>
        <PageHeader back={back} title={field.name} />
        <FieldEditor
          field={field}
          varieties={varieties as never}
          areaUnit={areaUnit}
          startOpen={sp.edit === 'sowing' ? 'sowing' : sp.edit === 'details' ? 'details' : null}
          summary={meta}
          actions={<ButtonLink href={`/${locale}/ask?field_id=${field.id}`} variant="secondary" icon={<Mic size={20} aria-hidden="true" />}>{t('field.askAbout')}</ButtonLink>}
        />

        <section aria-labelledby="decision-h" className={styles.decision}>
          <h2 id="decision-h" className="visually-hidden">{t('field.decision')}</h2>
          {decision ? (
            <DecisionCard variant="full" field={{ id: field.id, name: field.name, crop: field.crop }} decision={decision} ctx={ctx} extra={decisionExtra} renderedAt={renderedAt}
              abstainAction={decision.abstain_reason === 'missing_field_input' ? <ButtonLink href={`/${locale}/field/${field.id}?edit=sowing`}>{t('abstain.missing_field_input.action')}</ButtonLink> : undefined} />
          ) : (
            // No decision stored yet: a new or just-edited field is being worked out in the background.
            <div className={styles.pending} role="status">
              <p>{t('home.working', { field: field.name })}</p>
              <RefreshWhilePending />
            </div>
          )}
        </section>

        <Section id="stage-h" title={t('field.stage.title')}>
          <Card>
            <StageTimeline stage={field.stage} t={t} locale={locale} now={now}
              unknownAction={<ButtonLink href={`/${locale}/field/${field.id}?edit=sowing`} variant="secondary">{t('abstain.missing_field_input.action')}</ButtonLink>} />
          </Card>
        </Section>

        <Section id="risks-h" title={t('field.risks.title')}>
          {fc ? (
            <Disclosure label={t('field.risks.forecast7')}>
              <WeatherSummary forecast={fc} fieldName={field.name} ctx={ctx} />
            </Disclosure>
          ) : <p className={styles.muted}>{t('wx.unavailable')}</p>}
          {!active.ok && !field.risks?.length ? (
            <RouteError message={t('state.sectionError', { section: t('section.risks') })} action={<RetryButton />} />
          ) : risks.length === 0 ? (
            <p className={styles.positive}><CircleCheck size={20} aria-hidden="true" /> {t('field.risks.none')}</p>
          ) : (
            <div className={styles.riskGrid}>
              {risks.map((r, i) => (
                <Card key={`${r.kind}-${i}`} variant="risk" level={r.level} as="article" aria-labelledby={`risk-${i}`}>
                  <div className={styles.riskHead}>
                    <h3 id={`risk-${i}`} className={styles.riskTitle}><KindIcon kind={r.kind} size={24} /> {kindLabel(t, r.kind)}</h3>
                    <RiskBadge level={r.level} t={t} />
                    <span className={styles.pct}>{pctText(t, r.probability, locale)}</span>
                  </div>
                  <ProbabilityMeter label={t(`chance.meterLabel.${r.kind}`)} value={r.probability} level={r.level} variant="compact" t={t} locale={locale} />
                  {(r.kind === 'frost' || r.kind === 'heatwave') && (fc || eventOf(r)) ? (
                    <TemperatureBand kind={r.kind === 'frost' ? 'frost' : 'heat'} series={forecastSeries(fc, r.kind === 'frost' ? 'frost' : 'heat')} event={eventOf(r)}
                      thresholdC={r.threshold_c ?? null} thresholdLabel={thresholdLabel} level={r.level}
                      sources={fc ? [{ ...fromSourceRef(fc.source), kind: 'forecast', stale: fc.stale }] : riskSources(r)} stale={fc?.stale} ctx={ctx} />
                  ) : null}
                  {r.kind === 'heavy_rain' && fc ? (
                    <ul className={styles.rainList} aria-label={t('wx.rain')}>
                      {fc.rows.slice(0, 7).map((row) => (
                        <li key={row.valid_date} className={styles.rainRow}>
                          <span>{formatDateShort(row.valid_date, locale, now)}</span>
                          <span className={styles.rainBar} aria-hidden="true"><span style={{ width: `${Math.min(100, ((row.rain_mm ?? 0) / Math.max(1, ...fc.rows.map((x) => x.rain_mm ?? 0))) * 100)}%` }} /></span>
                          <span className="tabular">{row.rain_mm === null ? t('market.route.noData') : formatWithUnit(row.rain_mm, t('units.mm'), locale)}</span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  <Disclosure label={t('common.whyThis')}>
                    <dl className={styles.why}>
                      <dt>{t('field.why.inputs')}</dt>
                      <dd>
                        <ul className={styles.inputs}>
                          {typeof r.tmin_c === 'number' ? <li>{t('decision.why.forecast', { value: formatTemp(r.tmin_c, locale, unit) })}{typeof r.band_low_c === 'number' && typeof r.band_high_c === 'number' ? ` (${t('decision.why.range', { low: formatTemp(r.band_low_c, locale, unit), high: formatTemp(r.band_high_c, locale, unit) })})` : ''}</li> : null}
                          {EVIDENCE_KEYS.filter((k) => r.evidence?.[k] !== undefined && r.evidence?.[k] !== null).map((k) => {
                            const v = r.evidence[k];
                            let text = String(v);
                            if (k === 'forecast_fetched_at' && typeof v === 'string') text = formatDateTime(v, locale, now);
                            if (k === 'station_distance_km' && typeof v === 'number') text = formatWithUnit(v, t('units.km'), locale, 1);
                            if (k === 'field_elevation_m' && typeof v === 'number') text = formatWithUnit(v, 'm', locale);
                            if (k === 'gdd_cum' && typeof v === 'number') text = formatNumber(v, locale);
                            if (k === 'forecast_rain_mm' && typeof v === 'number') text = formatWithUnit(v, t('units.mm'), locale, 1);
                            if (k === 'ensemble_members' && typeof v === 'number') text = formatNumber(v, locale);
                            if (k === 'method' && typeof v === 'string') text = t(`field.evidence.method.${v}`);
                            return <li key={k}>{t(`field.evidence.${k}`)}: <span lang={k === 'station' || k === 'forecast_source' || k === 'rule' ? 'en' : undefined}>{text}</span></li>;
                          })}
                        </ul>
                      </dd>
                      {typeof r.threshold_c === 'number' ? (<><dt>{t('field.why.threshold')}</dt><dd>{formatTemp(r.threshold_c, locale, unit)} ({thresholdLabel})</dd></>) : null}
                      {r.window_start && r.window_end ? (<><dt>{t('field.why.window')}</dt><dd>{formatDateTime(r.window_start, locale, now)} - {formatTime(r.window_end, locale)}</dd></>) : null}
                      <dt>{t('field.why.model')}</dt>
                      <dd lang="en">{r.model_version}</dd>
                      {r.evidence?.method === 'rule' ? <dd>{t('state.simpleEstimate')}</dd> : null}
                      {r.evidence?.skill_status && r.evidence.skill_status !== 'demonstrated' ? <dd className={styles.limit}>{t(`state.skill.${r.evidence.skill_status}`)}</dd> : null}
                      <dt>{t('field.why.sources')}</dt>
                      <dd><SourceLine sources={riskSources(r)} t={t} locale={locale} now={now} /></dd>
                      {r.kind === 'frost' ? <dd className={styles.limit}>{t('field.about.limitFrost')}</dd> : null}
                      {r.kind === 'heavy_rain' ? <dd className={styles.limit}>{t('field.about.limitRain')}</dd> : null}
                      {r.kind === 'transport' ? <dd className={styles.limit}>{t('field.about.limitTransport')}</dd> : null}
                    </dl>
                  </Disclosure>
                </Card>
              ))}
            </div>
          )}
        </Section>

        {d && drive && d.action_by && drive.level !== 'none' ? (
          <Section id="act-h" title={t('field.act.title')}>
            <Card>
              <ActionWindow actionBy={d.action_by} windowStart={drive.window_start} windowEnd={drive.window_end} kind={drive.kind} level={drive.level} t={t} locale={locale} now={now} />
            </Card>
          </Section>
        ) : null}

        <div className={styles.twoCol}>
          <Section id="market-h" title={t('field.market.title')} action={<ButtonLink href={`/${locale}/market?field_id=${field.id}`} variant="text">{t('field.market.seeMarket')}</ButtonLink>}>
            <Card>
              {d?.market ? (
                <div className={styles.stack}>
                  <PriceBand prices={null} forecast={null} summary={d.market} crop={field.crop} days={30} variant="row" ctx={ctx} />
                  {d.market.arrival_qtl !== null ? <p>{t('field.market.arrivals', { value: formatWithUnit(d.market.arrival_qtl, t('units.qtl'), locale) })}</p> : null}
                  <RecommendationBand recommendation={d.recommendation} variant={recVariant} ctx={ctx} headingLevel={3} />
                </div>
              ) : (
                <p className={styles.muted}>{t('home.marketUnavailable')}</p>
              )}
            </Card>
          </Section>

          <Suspense fallback={<Section id="transport-h" title={t('field.transport.title')}><Card><Skeleton height={120} radius="md" /></Card></Section>}>
            <TransportSection fieldId={field.id} ctx={ctx} />
          </Suspense>
        </div>

        <Section id="history-h" title={t('field.history.title')}>
          {!history.ok ? (
            <RouteError message={t('state.sectionError', { section: t('section.history') })} action={<RetryButton />} />
          ) : !hadRisk ? (
            <p className={styles.positive}><CircleCheck size={20} aria-hidden="true" /> {t('state.noAlerts30d')}</p>
          ) : (
            <table className={styles.history}>
              <caption className="visually-hidden">{t('field.history.title')}</caption>
              <thead><tr><th scope="col">{t('field.history.date')}</th><th scope="col">{t('field.history.decision')}</th><th scope="col">{t('field.history.outcome')}</th><th scope="col">{t('field.history.feedback')}</th></tr></thead>
              <tbody>
                {historyItems.map((h, i) => {
                  const dec = h.decision;
                  const top = !isAbstention(dec) ? topRisk(dec.risks) : null;
                  const o = h.outcome;
                  const kindText = top ? kindLabel(t, top.kind) : '';
                  return (
                    <tr key={`${dec.decision_date}-${i}`}>
                      <th scope="row">{formatDateShort(dec.decision_date, locale, now)}</th>
                      <td data-label={t('field.history.decision')}>
                        {isAbstention(dec) ? t('field.history.abstained', { title: t(`abstain.${dec.abstain_reason}.title`) })
                          : <>{top && top.level !== 'none' ? <RiskBadge level={top.level} kind={top.kind} size="sm" t={t} /> : null} <span>{dec.headline}</span></>}
                      </td>
                      <td data-label={t('field.history.outcome')}>
                        {o.status === 'confirmed' ? (
                          <span className={styles.outcome} data-tone="success"><CheckCheck size={16} aria-hidden="true" /> {typeof o.observed_value_c === 'number'
                            ? t('field.history.confirmed', { kind: kindText || levelLabel(t, 'none'), value: formatTemp(o.observed_value_c, locale, unit), source: o.source ?? '' })
                            : t('field.history.confirmedNoValue', { source: o.source ?? '' })}{o.observed_on ? ` · ${formatDateShort(o.observed_on, locale, now)}` : ''}</span>
                        ) : o.status === 'did_not_happen' ? (
                          <span className={styles.outcome}><CircleMinus size={16} aria-hidden="true" /> {typeof o.observed_value_c === 'number' ? t('field.history.didNot', { value: formatTemp(o.observed_value_c, locale, unit) }) : t('field.history.didNotNoValue')}{o.source ? ` (${o.source})` : ''}</span>
                        ) : (
                          <span className={styles.outcome} data-tone="muted"><Clock size={16} aria-hidden="true" /> {t('field.history.pending')}</span>
                        )}
                      </td>
                      <td data-label={t('field.history.feedback')}>
                        {h.alerts.map((a) => <FeedbackButton key={a.id} alertId={a.id} initial={a.feedback} />)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Section>

        <Section id="about-h" title={t('field.about.title')}>
          <Card>
            <dl className={styles.about}>
              {d ? (<><dt>{t('field.about.models')}</dt><dd lang="en">{Object.entries(d.model_versions).map(([k, v]) => `${k}: ${v}`).join(' · ')}</dd></>) : null}
              {d?.sources?.length ? (<><dt>{t('field.about.sources')}</dt><dd><ul className={styles.sourceList}>{d.sources.map((s, i) => <li key={i}><SourceLine sources={[fromSourceRef(s)]} t={t} locale={locale} now={now} /></li>)}</ul></dd></>) : null}
              <dt>{t('field.about.limits')}</dt>
              <dd>
                <ul className={styles.limits}>
                  {/* Localized versions of the engine's limitations (its own list is English-only), each once. */}
                  <li>{t('field.about.limitFrost')}</li>
                  {routeKnown ? <li>{t('field.about.limitTransport')}</li> : null}
                  {d?.market && d.market.forecast_available === false ? <li>{t('field.about.limitPrice')}</li> : null}
                  {d?.market && d.market.source === 'synthetic_seed' ? <li>{t('state.syntheticSource')}</li> : null}
                </ul>
              </dd>
            </dl>
          </Card>
        </Section>
        {fc?.stale ? <Banner variant="info" icon="info">{t('state.stale.card', { time: formatDateTime(fc.source.fetched_at, locale, now) })}</Banner> : null}
      </PageMain>
    </>
  );
}

async function TransportSection({ fieldId, ctx }: { fieldId: number; ctx: ViewCtx }) {
  const { t } = ctx;
  const transport = await getTransportRisk(fieldId);
  const tr: TransportRiskResponse | null = transport.ok ? transport.data : null;
  if (tr && !tr.available && tr.unavailable_reason === 'route_unknown') return null; // no route to a mandi: hidden (PRD §7.7)
  return (
    <Section id="transport-h" title={t('field.transport.title')}>
      <Card>
        {tr && tr.available ? <RouteStrip risk={tr} ctx={ctx} compact headingId="transport-h" />
          : tr && tr.unavailable_reason === 'forecast_stale' ? <p className={styles.muted}>{t('market.route.forecastStale')}</p>
            : <RouteError message={t('state.sectionError', { section: t('section.transport') })} action={<RetryButton />} />}
      </Card>
    </Section>
  );
}
