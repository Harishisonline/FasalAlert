import { scaleLinear, scaleTime } from 'd3-scale';
import { area, line } from 'd3-shape';
import type { Crop, MarketSummary, PriceForecastResponse, PricesResponse } from '@fasalalert/shared/api';
import { ChartFrame, DataTable, GridLines, PathMark, VB_W, VRule, chartStyles, type OverlayLabel } from '@/components/Chart';
import { SampleTag } from '@/components/UI/Badges';
import { Toggletip } from '@/components/UI/Toggletip';
import { SourceLine } from '@/components/Risk/SourceLine';
import { MINUS, daysBetween, formatDateShort, formatRupees, formatWithUnit, istDateKey, toDate } from '@/lib/format';
import { trendRead } from '@/lib/risk';
import { cropLabel, fromSourceRef, pctText, type ViewCtx } from '@/lib/view';
import { RangeToggle } from './RangeToggle';
import styles from './PriceBand.module.css';

export interface PriceBandProps {
  prices: PricesResponse | null;
  forecast: PriceForecastResponse | null;
  summary: MarketSummary | null;
  crop: Crop;
  days: 30 | 90;
  variant?: 'chart' | 'row';
  ctx: ViewCtx;
}

interface P { date: string; modal: number | null }

function median(xs: number[]): number | null {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2;
}

export function PriceBand({ prices, forecast, summary, crop, days, variant = 'chart', ctx }: PriceBandProps) {
  const { t, locale, now } = ctx;
  const series: P[] = (prices?.series ?? []).map((p) => ({ date: p.date, modal: p.modal_rs_qtl })).sort((a, b) => a.date.localeCompare(b.date));
  const withModal = series.filter((p) => p.modal !== null) as { date: string; modal: number }[];
  const last = withModal[withModal.length - 1] ?? null;
  const modal = last?.modal ?? summary?.modal_rs_qtl ?? null;
  const modalDate = last?.date ?? summary?.price_date ?? null;
  const synthetic = Boolean(prices?.synthetic);
  const qtl = t('units.perQtl');

  if (modal === null) return <p className={styles.unavailable}>{t('market.price.noHistory')}</p>;

  const isOld = modalDate ? daysBetween(modalDate, istDateKey(now)) > 1 : false;
  const med = summary?.median_5d ?? median(withModal.slice(-5).map((p) => p.modal));
  const fromForecast = Boolean(forecast?.available && forecast.points.length);
  const fpts = fromForecast ? [...forecast!.points].sort((a, b) => a.date.localeCompare(b.date)) : [];
  // The R4 row may only have the decision's market summary (PRD §11.1 forecast_p10/p50/p90).
  const summaryPt = !forecast && summary && summary.forecast_available !== false && summary.forecast_p10 !== null && summary.forecast_p50 !== null && summary.forecast_p90 !== null
    ? { date: '', p10: summary.forecast_p10, p50: summary.forecast_p50, p90: summary.forecast_p90 } : null;
  const available = fromForecast || Boolean(summaryPt);
  const endPt = fpts[fpts.length - 1] ?? summaryPt;
  const horizon = forecast?.horizon_days ?? summary?.horizon_days ?? fpts.length;
  const trend = endPt ? trendRead(modal, endPt.p10, endPt.p50, endPt.p90) : null;
  const p50 = endPt?.p50 ?? summary?.forecast_p50 ?? null;
  const loss = summary?.expected_transport_loss_rs_qtl ?? null;
  const showNet = p50 !== null && loss !== null && loss > 0;
  const hist = forecast?.historical_range ?? null;

  const trendText = trend
    ? `${t(trend.direction === 'up' ? 'market.price.up' : trend.direction === 'down' ? 'market.price.down' : 'market.price.flat', { horizon })}${trend.wide ? `, ${t('market.price.wide')}` : ''}`
    : null;

  const sources = [
    ...(prices?.sources ?? []).map((s) => fromSourceRef(s, { kind: s.synthetic || synthetic ? 'synthetic' : 'market' })),
  ];

  const head = (
    <div className={styles.head}>
      <p className={styles.big}>
        <span className={styles.value}>{formatRupees(modal, locale)}</span>
        <span className={styles.unit}>{qtl}</span>
        {modalDate ? <span className={styles.meta}>{isOld ? t('market.price.lastPrice', { date: formatDateShort(modalDate, locale, now) }) : t('market.price.modal', { date: formatDateShort(modalDate, locale, now) })}</span> : null}
        {synthetic ? <SampleTag label={t('common.sampleData')} /> : null}
      </p>
      {med !== null ? <p className={styles.stat}>{t('market.price.median', { value: formatRupees(med, locale) })}</p> : null}
      {trendText ? <p className={styles.trend}>{trendText}</p> : null}
      {!available ? (
        <p className={styles.note}>{forecast?.unavailable_reason === 'not_beating_baseline' ? t('market.price.notBeating') : t('market.price.forecastUnavailable')}</p>
      ) : null}
    </div>
  );

  const netRow = showNet ? (
    <div className={styles.net}>
      <p className={styles.netTitle}>
        {t('market.price.net')}
        <Toggletip label={t('market.price.netExplainLabel')}>{t('market.price.netExplain', { crop: cropLabel(t, crop, true) })}</Toggletip>
      </p>
      <p className={styles.netRow} aria-label={t('market.price.netAria', { p50: formatRupees(p50!, locale), loss: formatRupees(loss!, locale), net: formatRupees(p50! - loss!, locale) })}>
        <span aria-hidden="true"><span className={styles.netLabel}>{t('market.price.netExpected')}</span> {formatRupees(p50!, locale)}</span>
        <span aria-hidden="true"> {MINUS} <span className={styles.netLabel}>{t('market.price.netLoss')}</span> {formatRupees(loss!, locale)}</span>
        <span aria-hidden="true" className={styles.netResult}> = {formatRupees(p50! - loss!, locale)} {qtl}</span>
      </p>
    </div>
  ) : null;

  const rangeText = endPt
    ? t('market.price.expected', { low: formatRupees(endPt.p10, locale), high: formatRupees(endPt.p90, locale), horizon })
    : hist ? t('market.price.histRange', { low: formatRupees(hist.low, locale), high: formatRupees(hist.high, locale), from: formatDateShort(hist.from, locale, now), to: formatDateShort(hist.to, locale, now) }) : null;

  if (variant === 'row') {
    return (
      <div className={styles.row}>
        {head}
        {rangeText ? <p>{rangeText}</p> : null}
        {netRow}
        <SourceLine sources={sources} t={t} locale={locale} now={now} compact />
      </div>
    );
  }

  // Chart: history (last N days) plus the forecast horizon.
  const cut = new Date(toDate(last?.date ?? istDateKey(now)).getTime() - days * 86_400_000);
  const shown = series.filter((p) => toDate(p.date) >= cut);
  const height = 200;
  const pad = { top: 20, bottom: 12 };
  const histBandEnd = !available && hist ? new Date(toDate(last?.date ?? istDateKey(now)).getTime() + (horizon || 7) * 86_400_000) : null;
  const allDates = [...shown.map((p) => toDate(p.date).getTime()), ...fpts.map((p) => toDate(p.date).getTime()), ...(histBandEnd ? [histBandEnd.getTime()] : [])];
  const values = [...shown.flatMap((p) => (p.modal === null ? [] : [p.modal])), ...fpts.flatMap((p) => [p.p10, p.p90]), ...(histBandEnd && hist ? [hist.low, hist.high] : [])];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const padV = Math.max((hi - lo) * 0.1, hi * 0.02, 10);
  const y = scaleLinear().domain([lo - padV, hi + padV]).nice(4).range([height - pad.bottom, pad.top]);
  const x = scaleTime().domain([new Date(Math.min(...allDates)), new Date(Math.max(...allDates))]).range([0, VB_W]);
  const ticks = y.ticks(4).slice(0, 4);
  const xp = (d: string | Date) => (x(toDate(d as string)) / VB_W) * 100;

  const histLine = line<P>().defined((p) => p.modal !== null).x((p) => x(toDate(p.date))).y((p) => y(p.modal ?? 0));
  const fLine = line<{ date: string; v: number }>().x((p) => x(toDate(p.date))).y((p) => y(p.v));
  const fArea = area<{ date: string; p10: number; p90: number }>().x((p) => x(toDate(p.date))).y0((p) => y(p.p10)).y1((p) => y(p.p90));
  const anchor = last ? [{ date: last.date, v: last.modal, p10: last.modal, p90: last.modal }] : [];
  const fSeries = [...anchor, ...fpts.map((p) => ({ date: p.date, v: p.p50, p10: p.p10, p90: p.p90 }))];

  const overlays: OverlayLabel[] = [];
  if (endPt) {
    overlays.push({ xPct: 100, y: y(endPt.p90) - 2, text: `p90 ${formatRupees(endPt.p90, locale)}`, align: 'end', tone: 'muted' });
    overlays.push({ xPct: 100, y: y(endPt.p50) - 2, text: `p50 ${formatRupees(endPt.p50, locale)}`, align: 'end', tone: 'strong' });
    overlays.push({ xPct: 100, y: y(endPt.p10) + 2, text: `p10 ${formatRupees(endPt.p10, locale)}`, align: 'end', tone: 'muted', below: true });
  }
  if (histBandEnd && hist && last) overlays.push({ xPct: xp(last.date), y: y(hist.high) - 2, text: t('market.price.histOnly'), tone: 'muted' });
  if (shown.length) overlays.push({ xPct: xp(shown[0]!.date), y: pad.top - 2, text: t('market.price.observed'), tone: 'muted' });

  const firstDate = shown[0]?.date;
  const xLabels = [
    ...(firstDate ? [{ xPct: 0, text: formatDateShort(firstDate, locale, now), align: 'start' as const }] : []),
    ...(last ? [{ xPct: xp(last.date), text: t('market.price.today') }] : []),
    ...(endPt ? [{ xPct: 100, text: formatDateShort(endPt.date, locale, now), align: 'end' as const }] : []),
  ];

  const readout = [
    ...shown.filter((p) => p.modal !== null).map((p) => ({ xPct: xp(p.date), label: t('market.price.readout', { date: formatDateShort(p.date, locale, now), value: formatRupees(p.modal!, locale) }) })),
    ...fpts.map((p) => ({ xPct: xp(p.date), label: t('market.price.readoutForecast', { date: formatDateShort(p.date, locale, now), p50: formatRupees(p.p50, locale), p10: formatRupees(p.p10, locale), p90: formatRupees(p.p90, locale) }) })),
  ];
  const summaryText = [
    firstDate && last ? t('market.price.summaryHistory', { days, first: formatDateShort(firstDate, locale, now), last: formatDateShort(last.date, locale, now) }) : '',
    trendText ? `${trendText}.` : '',
    rangeText ? `${rangeText}.` : '',
  ].filter(Boolean).join(' ');

  const table = (
    <DataTable
      caption={t('market.price.chartTitle')}
      columns={[t('market.price.col.date'), t('market.price.col.modal'), t('market.price.col.p10'), t('market.price.col.p50'), t('market.price.col.p90')]}
      rows={[
        ...shown.map((p) => [formatDateShort(p.date, locale, now), p.modal === null ? t('market.arrivals.noData') : formatRupees(p.modal, locale), '', '', '']),
        ...fpts.map((p) => [formatDateShort(p.date, locale, now), '', formatRupees(p.p10, locale), formatRupees(p.p50, locale), formatRupees(p.p90, locale)]),
      ]}
    />
  );

  return (
    <div className={styles.panel}>
      {head}
      <ChartFrame
        title={t('market.price.chartTitle')}
        summary={summaryText}
        ariaLabel={t('market.price.chartTitle')}
        height={height}
        yLabels={ticks.map((v) => ({ y: y(v), text: formatWithUnit(v, '', locale).trim() }))}
        xLabels={xLabels}
        overlays={overlays}
        points={readout}
        table={table}
        showTableLabel={t('common.showTable')}
        hideTableLabel={t('common.hideTable')}
        footer={<RangeToggle days={days} />}
      >
        <defs>
          <pattern id="fa-hist-stripes" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="8" height="8" fill="var(--color-bg-surface)" />
            <rect width="4" height="8" fill="var(--mk-hist-range)" />
          </pattern>
        </defs>
        <GridLines ys={ticks.map((v) => y(v))} />
        {histBandEnd && hist && last ? (
          <rect x={x(toDate(last.date))} width={Math.max(0, x(histBandEnd) - x(toDate(last.date)))} y={y(hist.high)} height={Math.max(0, y(hist.low) - y(hist.high))} className={chartStyles.histBand} vectorEffect="non-scaling-stroke" />
        ) : null}
        {available ? <path d={fArea(fSeries) ?? ''} className={chartStyles.mkBand} vectorEffect="non-scaling-stroke" /> : null}
        <PathMark d={histLine(shown)} className={synthetic ? chartStyles.synthetic : chartStyles.price} />
        {available ? <PathMark d={fLine(fSeries)} className={chartStyles.p50} dash /> : null}
        {last ? <VRule x={x(toDate(last.date))} top={pad.top - 6} bottom={height} className={chartStyles.nowRule} /> : null}
      </ChartFrame>
      {rangeText ? <p className={styles.range}>{rangeText}</p> : null}
      {available ? <p className={styles.histNote}>{endPt ? null : null}</p> : hist ? <p className={styles.histNote}>{t('market.price.histOnly')}</p> : null}
      {netRow}
      {forecast?.beats_baseline_pct != null ? <p className={styles.baseline}>{t('market.price.baselineNote', { pct: pctText(t, forecast.beats_baseline_pct > 1 ? forecast.beats_baseline_pct / 100 : forecast.beats_baseline_pct, locale) })}</p> : null}
      <SourceLine sources={[...sources, ...(forecast?.model_version ? [{ label: forecast.model_version, at: forecast.trained_at, kind: 'model' as const }] : [])]} t={t} locale={locale} now={now} compact />
    </div>
  );
}
