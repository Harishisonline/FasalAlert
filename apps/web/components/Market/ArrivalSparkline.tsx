import type { PricePoint } from '@fasalalert/shared/api';
import { DataTable } from '@/components/Chart';
import { daysBetween, formatDateShort, formatWithUnit, istDateKey, toDate } from '@/lib/format';
import type { ViewCtx } from '@/lib/view';
import { TableToggle } from './TableToggle';
import styles from './ArrivalSparkline.module.css';

/**
 * 14 days of arrivals (PRD §7.7, design.md 14.14). Missing days are a gap with a small "no data"
 * tick on the baseline, never a zero bar. A typical line is drawn only if the API supplies one.
 */
export function ArrivalSparkline({ series, market, ctx }: { series: PricePoint[]; market: string; ctx: ViewCtx }) {
  const { t, locale, now } = ctx;
  const byDate = new Map(series.map((p) => [p.date, p.arrival_qtl]));
  const lastDate = [...series].filter((p) => p.arrival_qtl !== null).map((p) => p.date).sort().pop() ?? null;
  const end = lastDate ?? istDateKey(now);
  const days = Array.from({ length: 14 }, (_, i) => istDateKey(new Date(toDate(end).getTime() - (13 - i) * 86_400_000)));
  const values = days.map((d) => byDate.get(d) ?? null);
  const present = values.filter((v): v is number => v !== null);
  const unit = t('units.qtl');
  if (present.length === 0) return <p className={styles.none}>{t('market.arrivals.none')}</p>;
  const max = Math.max(...present);
  const min = Math.min(...present);
  const lastVal = lastDate ? byDate.get(lastDate) ?? null : null;
  const isToday = lastDate ? daysBetween(lastDate, istDateKey(now)) === 0 : false;
  const summary = lastVal === null || lastVal === undefined ? t('market.arrivals.none')
    : isToday ? t('market.arrivals.today', { value: formatWithUnit(lastVal, unit, locale), market })
      : t('market.arrivals.last', { value: formatWithUnit(lastVal, unit, locale), market, date: formatDateShort(lastDate!, locale, now) });

  return (
    <div className={styles.wrap}>
      <p className={styles.summary}>{summary}</p>
      <div className={styles.chart} role="img" aria-label={summary}>
        <div className={styles.scale} aria-hidden="true">
          <span>{formatWithUnit(max, unit, locale)}</span>
          <span>{formatWithUnit(min, unit, locale)}</span>
        </div>
        <div className={styles.bars} aria-hidden="true">
          {values.map((v, i) => (
            <span key={days[i]} className={styles.slot}>
              {v === null ? <span className={styles.missing} /> : (
                <span className={styles.bar} data-today={days[i] === lastDate || undefined} style={{ height: `${Math.max(4, (v / max) * 100)}%` }}>
                  {days[i] === lastDate ? <span className={styles.valueLabel}>{formatWithUnit(v, '', locale).trim()}</span> : null}
                </span>
              )}
            </span>
          ))}
        </div>
      </div>
      <TableToggle showLabel={t('common.showTable')} hideLabel={t('common.hideTable')}>
        <DataTable
          caption={t('market.arrivals.title')}
          columns={[t('market.arrivals.col.date'), t('market.arrivals.col.value')]}
          rows={days.map((d, i) => [formatDateShort(d, locale, now), values[i] === null ? t('market.arrivals.noData') : formatWithUnit(values[i]!, unit, locale)])}
        />
      </TableToggle>
    </div>
  );
}
