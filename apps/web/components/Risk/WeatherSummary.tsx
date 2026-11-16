import type { ForecastResponse } from '@fasalalert/shared/api';
import { CloudRain } from '@/components/Icon';
import { formatDateShort, formatDateTime, formatPercent, formatTemp, formatWeekday, formatWithUnit } from '@/lib/format';
import { fromSourceRef, type ViewCtx } from '@/lib/view';
import { SourceLine } from './SourceLine';
import styles from './WeatherSummary.module.css';

/**
 * 7-day forecast strip (design.md 14.5). No sun or cloud icons: the forecast rows have no
 * condition field, so only rainfall gets an icon.
 */
export function WeatherSummary({ forecast, fieldName, ctx }: { forecast: ForecastResponse; fieldName: string; ctx: ViewCtx }) {
  const { t, locale, now, unit } = ctx;
  const rows = forecast.rows.slice(0, 7);
  if (rows.length === 0) return <p className={styles.unavailable}>{t('wx.unavailable')}</p>;
  const issued = rows[0]?.issued_at ?? forecast.source.fetched_at;
  return (
    <div className={styles.wrap}>
      <div className={styles.scroll} tabIndex={0} role="region" aria-label={t('field.risks.forecast7')}>
        <table className={styles.table} style={{ ['--cols' as string]: rows.length }}>
          <caption className="visually-hidden">
            {t('wx.caption', { field: fieldName, source: forecast.source.label, time: formatDateTime(issued, locale, now) })}
          </caption>
          <thead>
            <tr>
              <th scope="row" className="visually-hidden">{t('wx.day')}</th>
              {rows.map((r) => (
                <th key={r.valid_date} scope="col" className={styles.day}>
                  <span className={styles.short}>{formatWeekday(r.valid_date, locale).slice(0, 2)} {formatDateShort(r.valid_date, locale, now).split(' ')[0]}</span>
                  <span className={styles.long}>{formatWeekday(r.valid_date, locale)} {formatDateShort(r.valid_date, locale, now)}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row" className="visually-hidden">{t('wx.tmax')}</th>
              {rows.map((r) => <td key={r.valid_date} className={styles.tmax}>{r.tmax_c === null ? '' : formatTemp(r.tmax_c, locale, unit)}</td>)}
            </tr>
            <tr>
              <th scope="row" className="visually-hidden">{t('wx.tmin')}</th>
              {rows.map((r) => <td key={r.valid_date} className={styles.tmin}>{r.tmin_c === null ? '' : formatTemp(r.tmin_c, locale, unit)}</td>)}
            </tr>
            <tr>
              <th scope="row" className="visually-hidden">{t('wx.rain')}</th>
              {rows.map((r) => (
                <td key={r.valid_date} className={styles.rain}>
                  {r.rain_mm !== null && r.rain_mm >= 1 ? (
                    <><CloudRain size={16} aria-hidden="true" /> {formatWithUnit(r.rain_mm, t('units.mm'), locale)}</>
                  ) : r.rain_mm === null ? '' : <span className={styles.noRain}>{t('wx.noRain')}</span>}
                  {r.precip_prob !== null ? <span className={styles.long}>{formatPercent(r.precip_prob > 1 ? r.precip_prob / 100 : r.precip_prob, locale) ?? ''}</span> : null}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      <SourceLine sources={[{ ...fromSourceRef(forecast.source), kind: 'forecast', at: issued, stale: forecast.stale }]} t={t} locale={locale} now={now} compact />
    </div>
  );
}
