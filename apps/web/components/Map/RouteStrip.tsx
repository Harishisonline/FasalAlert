import type { RiskLevel, TransportRiskResponse } from '@fasalalert/shared/api';
import { ExternalLink, LevelIcon, Route, TriangleAlert } from '@/components/Icon';
import { SourceLine } from '@/components/Risk/SourceLine';
import { formatDateShort, formatDateTime, formatWeekday, istDateKey } from '@/lib/format';
import { transportLevel } from '@/lib/risk';
import { isSafeHttpUrl, levelLabel, pctText, type ViewCtx } from '@/lib/view';
import styles from './RouteStrip.module.css';

const TRANSPORT_NOTE_FALLBACK = 'field.about.limitTransport';

/**
 * RouteRiskStrip (design.md 14.12): 7-day chance of route disruption with plain labels. The legend
 * sentence is mandatory and verbatim; the words "closed" and "blocked" are never used. When IMD's
 * official highway warning is present it is shown above as the authoritative source (PRD §9.3).
 */
export function RouteStrip({ risk, ctx, compact, headingId }: { risk: TransportRiskResponse; ctx: ViewCtx; compact?: boolean; headingId?: string }) {
  const { t, locale, now } = ctx;
  const days = risk.days.slice(0, 7);
  const deadlineKey = risk.harvest_deadline ? istDateKey(risk.harvest_deadline) : null;
  const deadlineIdx = deadlineKey ? days.findIndex((d) => d.date === deadlineKey) : -1;
  const official = risk.official_warning;
  return (
    <div className={styles.wrap} data-compact={compact || undefined}>
      {risk.route_name ? (
        <p className={styles.route}><Route size={20} aria-hidden="true" /> <span lang="en">{risk.route_name}</span></p>
      ) : null}
      {official ? (
        <div className={styles.official} role="note">
          <p className={styles.officialTitle}><TriangleAlert size={20} aria-hidden="true" /> {t('market.route.official')}</p>
          <p>{official.text}</p>
          <p className={styles.officialSource}>
            {t('market.route.officialSource', { source: official.source, time: formatDateTime(official.issued_at, locale, now) })}
            {isSafeHttpUrl(official.url) ? (
              <a href={official.url} target="_blank" rel="noopener noreferrer" className={styles.link} aria-label={`${t('common.openSource', { label: official.source })} ${t('social.newTab')}`}>
                <ExternalLink size={16} aria-hidden="true" />
              </a>
            ) : null}
          </p>
        </div>
      ) : null}
      {official ? <p className={styles.modelLabel}>{t('market.route.model')}</p> : null}
      {risk.harvest_deadline ? (
        <p className={styles.deadline} id={headingId ? `${headingId}-deadline` : undefined}>
          {t('market.route.loadBy', { date: formatDateShort(risk.harvest_deadline, locale, now) })}
        </p>
      ) : null}
      <ol className={styles.strip}>
        {days.map((d, i) => {
          const level: RiskLevel = d.level ?? transportLevel(d.p_disruption);
          const dayName = `${formatWeekday(d.date, locale, 'long')} ${formatDateShort(d.date, locale, now)}`;
          const noData = !Number.isFinite(d.p_disruption);
          return (
            <li key={d.date} className={styles.cell} data-level={noData ? 'nodata' : level} data-deadline={i === deadlineIdx || undefined}
              aria-label={noData ? t('market.route.cellNoData', { day: dayName }) : t('market.route.cell', { day: dayName, pct: pctText(t, d.p_disruption, locale), level: levelLabel(t, level) })}>
              <span className={styles.weekday} aria-hidden="true">
                <span className={styles.short}>{formatWeekday(d.date, locale).slice(0, 2)}</span>
                <span className={styles.long}>{formatWeekday(d.date, locale)}</span>
              </span>
              <span className={styles.date} aria-hidden="true">{formatDateShort(d.date, locale, now).split(' ')[0]}</span>
              {noData ? <span className={styles.noData} aria-hidden="true">{t('market.route.noData')}</span> : (
                <>
                  <LevelIcon level={level} size={20} className={styles.icon} />
                  <span className={styles.pct} aria-hidden="true">{pctText(t, d.p_disruption, locale)}</span>
                </>
              )}
            </li>
          );
        })}
      </ol>
      <p className={styles.legend}>{risk.note || t(TRANSPORT_NOTE_FALLBACK)}</p>
      <SourceLine
        sources={[{ label: [risk.route_name, risk.model_version].filter(Boolean).join(' · '), at: risk.computed_at, kind: 'model' }]}
        t={t} locale={locale} now={now} compact
      />
    </div>
  );
}
