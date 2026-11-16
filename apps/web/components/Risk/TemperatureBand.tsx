import { scaleLinear, scaleTime } from 'd3-scale';
import { line } from 'd3-shape';
import type { RiskLevel } from '@fasalalert/shared/api';
import { ChartFrame, DataTable, Dots, GridLines, HRule, PathMark, VB_W, VRule, chartStyles, type OverlayLabel, type XLabel } from '@/components/Chart';
import { daysBetween, formatDateShort, formatTemp, formatTime, formatWeekday, istDateKey, toDate, toUnit } from '@/lib/format';
import { whenWord, type SourceItem, type ViewCtx } from '@/lib/view';
import { SourceLine } from './SourceLine';
import styles from './TemperatureBand.module.css';

export interface TemperatureBandProps {
  kind: 'frost' | 'heat';
  /** Forecast (and any observed) values. Daily values are placed at midday IST. */
  series: { at: string; valueC: number; observed: boolean }[];
  /** The event point with its band (interval mode, design.md 14.4). */
  event?: { at: string; valueC: number; lowC?: number | null; highC?: number | null } | null;
  thresholdC: number | null;
  thresholdLabel: string;
  level: RiskLevel;
  sources: SourceItem[];
  compact?: boolean;
  stale?: boolean;
  ctx: ViewCtx;
}

export function TemperatureBand({ kind, series, event, thresholdC, thresholdLabel, level, sources, compact, stale, ctx }: TemperatureBandProps) {
  const { t, locale, now, unit } = ctx;
  const pts = series.filter((p) => Number.isFinite(p.valueC)).sort((a, b) => toDate(a.at).getTime() - toDate(b.at).getTime());
  if (pts.length === 0 && !event) return <p className={styles.unavailable}>{t('tband.unavailable')}</p>;

  const height = compact ? 120 : 200;
  const pad = { top: 24, bottom: 12 };
  const u = (c: number) => toUnit(c, unit);
  const fmt = (c: number) => formatTemp(c, locale, unit);
  const hasBand = event && typeof event.lowC === 'number' && typeof event.highC === 'number';

  const values = [...pts.map((p) => p.valueC), ...(event ? [event.valueC] : []), ...(hasBand ? [event.lowC!, event.highC!] : []), ...(thresholdC !== null ? [thresholdC] : [])].map(u);
  let lo = Math.floor((Math.min(...values) - 2) / 2) * 2;
  let hi = Math.ceil((Math.max(...values) + 2) / 2) * 2;
  if (hi - lo < 4) { lo -= 2; hi += 2; }
  const y = scaleLinear().domain([lo, hi]).range([height - pad.bottom, pad.top]);

  const times = [...pts.map((p) => toDate(p.at).getTime()), ...(event ? [toDate(event.at).getTime()] : []), now.getTime()];
  const t0 = Math.min(...times) - 6 * 3600_000;
  const t1 = Math.max(...times) + 6 * 3600_000;
  const x = scaleTime().domain([new Date(t0), new Date(t1)]).range([0, VB_W]);
  const xPct = (iso: string | Date) => (x(toDate(iso as string)) / VB_W) * 100;

  const ticks = y.ticks(compact ? 3 : 4);
  const observed = pts.filter((p) => p.observed);
  const forecast = pts.filter((p) => !p.observed);
  const mk = line<{ at: string; valueC: number }>().x((p) => x(toDate(p.at))).y((p) => y(u(p.valueC)));

  const overlays: OverlayLabel[] = [];
  if (thresholdC !== null) {
    overlays.push({ xPct: 100, y: y(u(thresholdC)) - 2, text: t('tband.thresholdLabel', { label: thresholdLabel, value: fmt(thresholdC) }), align: 'end', tone: 'threshold', below: kind === 'heat' });
  }
  if (event) overlays.push({ xPct: xPct(event.at), y: y(u(event.valueC)) - 8, text: fmt(event.valueC), align: 'center', tone: 'event' });
  if (observed.length && !compact) overlays.push({ xPct: xPct(observed[0]!.at), y: pad.top - 4, text: t('tband.observed'), tone: 'muted' });
  if (forecast.length && !compact) overlays.push({ xPct: Math.min(85, xPct(forecast[0]!.at)), y: pad.top - 4, text: t('tband.forecast'), tone: 'muted' });

  // One x label per day: "Today", then the weekday.
  const days = new Map<string, string>();
  for (const p of pts) days.set(istDateKey(p.at), p.at);
  if (event) days.set(istDateKey(event.at), event.at);
  const xLabels: XLabel[] = [...days.entries()].map(([key, at]) => ({
    xPct: Math.min(96, Math.max(4, (x(new Date(`${key}T12:00:00+05:30`)) / VB_W) * 100)),
    text: daysBetween(istDateKey(now), key) === 0 ? t('tband.today') : formatWeekday(at, locale),
  }));

  const evIso = event?.at ?? null;
  const subject = event ?? (kind === 'frost' ? [...pts].sort((a, b) => a.valueC - b.valueC)[0] : [...pts].sort((a, b) => b.valueC - a.valueC)[0]);
  const summaryParts: string[] = [];
  if (subject) {
    const when = `${whenWord(t, subject.at, now, locale)}${evIso ? `, ${formatTime(subject.at, locale)}` : ''}`;
    summaryParts.push(t(kind === 'frost' ? 'tband.lowest' : 'tband.highest', { when, value: fmt(subject.valueC) }));
  }
  if (hasBand) summaryParts.push(t('tband.range', { low: fmt(event.lowC!), high: fmt(event.highC!) }));
  else if (event) summaryParts.push(t('tband.noBand'));
  if (thresholdC !== null) summaryParts.push(t('tband.thresholdSentence', { label: thresholdLabel, value: fmt(thresholdC) }));
  const summary = summaryParts.join(' ');

  const readout = [
    ...pts.map((p) => ({ xPct: xPct(p.at), label: t('tband.readout', { day: `${formatWeekday(p.at, locale)} ${formatDateShort(p.at, locale, now)}`, kind: p.observed ? t('tband.observed') : t('tband.forecast'), value: fmt(p.valueC) }) })),
    ...(event ? [{
      xPct: xPct(event.at),
      label: hasBand
        ? t('tband.readoutBand', { day: `${formatWeekday(event.at, locale)} ${formatTime(event.at, locale)}`, value: fmt(event.valueC), low: fmt(event.lowC!), high: fmt(event.highC!) })
        : t('tband.readout', { day: `${formatWeekday(event.at, locale)} ${formatTime(event.at, locale)}`, kind: t('tband.forecast'), value: fmt(event.valueC) }),
    }] : []),
  ].sort((a, b) => a.xPct - b.xPct);

  const sourceLabel = sources[0]?.label ?? '';
  const table = (
    <DataTable
      caption={t(kind === 'frost' ? 'tband.titleFrost' : 'tband.titleHeat')}
      columns={[t('tband.col.time'), t('tband.col.value'), t('tband.col.low'), t('tband.col.high'), t('tband.col.threshold'), t('tband.col.source')]}
      rows={[
        ...pts.map((p) => [`${formatWeekday(p.at, locale)} ${formatDateShort(p.at, locale, now)}`, `${fmt(p.valueC)}${p.observed ? ` (${t('tband.observed')})` : ''}`, '', '', thresholdC !== null ? fmt(thresholdC) : '', sourceLabel]),
        ...(event ? [[`${formatWeekday(event.at, locale)} ${formatTime(event.at, locale)}`, fmt(event.valueC), hasBand ? fmt(event.lowC!) : '', hasBand ? fmt(event.highC!) : '', thresholdC !== null ? fmt(thresholdC) : '', sourceLabel]] : []),
      ]}
    />
  );

  const ex = event ? x(toDate(event.at)) : 0;
  const bandTop = hasBand ? y(u(event.highC!)) : 0;
  const bandBottom = hasBand ? y(u(event.lowC!)) : 0;
  const est = event ? y(u(event.valueC)) : 0;
  const gradId = `tb-grad-${kind}-${Math.round(ex)}`;
  const breach = hasBand && thresholdC !== null
    ? kind === 'frost'
      ? u(event.lowC!) < u(thresholdC) ? { from: y(Math.min(u(thresholdC), u(event.highC!))), to: bandBottom } : null
      : u(event.highC!) > u(thresholdC) ? { from: bandTop, to: y(Math.max(u(thresholdC), u(event.lowC!))) } : null
    : null;

  return (
    <div className={styles.wrap} data-stale={stale || undefined}>
      <ChartFrame
        title={t(kind === 'frost' ? 'tband.titleFrost' : 'tband.titleHeat')}
        summary={summary}
        ariaLabel={t(kind === 'frost' ? 'tband.titleFrost' : 'tband.titleHeat')}
        height={height}
        yLabels={ticks.map((v) => ({ y: y(v), text: `${v}°` }))}
        xLabels={xLabels}
        overlays={overlays}
        points={readout}
        table={table}
        showTableLabel={t('common.showTable')}
        hideTableLabel={t('common.hideTable')}
        footer={<SourceLine sources={sources} t={t} locale={locale} now={now} compact />}
      >
        <GridLines ys={ticks.map((v) => y(v))} />
        {hasBand ? (
          <>
            <defs>
              <linearGradient id={gradId} gradientUnits="userSpaceOnUse" x1="0" x2="0" y1={bandTop} y2={bandBottom}>
                <stop offset="0" stopColor="var(--wx-band)" />
                <stop offset={String(Math.min(1, Math.max(0, (est - bandTop) / Math.max(1, bandBottom - bandTop))))} stopColor="var(--wx-forecast)" stopOpacity="0.55" />
                <stop offset="1" stopColor="var(--wx-band)" />
              </linearGradient>
            </defs>
            <line x1={ex} x2={ex} y1={bandTop} y2={bandBottom} stroke={`url(#${gradId})`} strokeWidth={12} strokeLinecap="butt" vectorEffect="non-scaling-stroke" />
            {breach ? <line x1={ex} x2={ex} y1={breach.from} y2={breach.to} className={chartStyles.breach} data-level={level} stroke="currentColor" strokeWidth={12} vectorEffect="non-scaling-stroke" style={{ color: `var(--risk-${level})` }} /> : null}
          </>
        ) : null}
        {thresholdC !== null ? <HRule y={y(u(thresholdC))} className={chartStyles.threshold} /> : null}
        <PathMark d={observed.length > 1 ? mk(observed) : null} className={chartStyles.observed} />
        <Dots points={observed.map((p) => ({ x: x(toDate(p.at)), y: y(u(p.valueC)) }))} className={chartStyles.observed} />
        <PathMark d={forecast.length > 1 ? mk(forecast) : null} className={chartStyles.forecast} dash />
        <Dots points={forecast.map((p) => ({ x: x(toDate(p.at)), y: y(u(p.valueC)) }))} className={chartStyles.forecast} hollow />
        <VRule x={x(now)} top={pad.top - 8} bottom={height} className={chartStyles.nowRule} />
        {event ? <Dots points={[{ x: ex, y: est }]} className={`${chartStyles.eventRing}`} hollow /> : null}
      </ChartFrame>
    </div>
  );
}
