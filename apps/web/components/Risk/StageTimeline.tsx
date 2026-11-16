import type { ReactNode } from 'react';
import type { StageSummary } from '@fasalalert/shared/api';
import type { Translator } from '@/lib/i18n';
import type { Locale } from '@/lib/locales';
import { IST, formatDateShort, formatNumber, toDate } from '@/lib/format';
import { intlLocale } from '@/lib/locales';
import { loc } from '@/lib/view';
import styles from './StageTimeline.module.css';

export interface StageTimelineProps {
  stage: StageSummary;
  t: Translator;
  locale: Locale;
  now: Date;
  /** Shown in the stage-unknown state: a button that opens Edit field (PRD §7.4). */
  unknownAction?: ReactNode;
}

/** 12-month band, the current stage highlighted, a GDD marker and the next stage (design.md 14.6). */
export function StageTimeline({ stage, t, locale, now, unknownAction }: StageTimelineProps) {
  if (!stage.stage || stage.timeline.length === 0) {
    return (
      <div className={styles.timeline} data-state="unknown">
        <div className={styles.unknownBand} aria-hidden="true" />
        <p className={styles.line}>{t('stage.unknownBand')}</p>
        {unknownAction}
      </div>
    );
  }
  const starts = stage.timeline.map((s) => toDate(s.start).getTime());
  const ends = stage.timeline.map((s) => toDate(s.end).getTime());
  const windowStart = new Date(Math.min(...starts));
  const monthStart = new Date(Date.UTC(windowStart.getUTCFullYear(), windowStart.getUTCMonth(), 1));
  const windowEnd = new Date(Date.UTC(monthStart.getUTCFullYear(), monthStart.getUTCMonth() + 12, 1));
  const from = monthStart.getTime();
  const span = windowEnd.getTime() - from;
  const pos = (ms: number) => Math.min(100, Math.max(0, ((ms - from) / span) * 100));
  const continues = Math.max(...ends) > windowEnd.getTime();
  const monthFmt = new Intl.DateTimeFormat(intlLocale(locale), { month: 'short', timeZone: IST });
  const months = Array.from({ length: 12 }, (_, i) => new Date(Date.UTC(monthStart.getUTCFullYear(), monthStart.getUTCMonth() + i, 15)));
  const nowPct = pos(now.getTime());
  const nowInWindow = now.getTime() >= from && now.getTime() <= windowEnd.getTime();
  const current = stage.stage_label ? loc(stage.stage_label, locale) : stage.stage;
  const next = stage.next_stage_label ? loc(stage.next_stage_label, locale) : stage.next_stage;

  return (
    <div className={styles.timeline}>
      <div className={styles.visual} aria-hidden="true">
        <div className={styles.months}>
          {months.map((m, i) => (
            <span key={m.toISOString()} className={styles.month} data-quarter={i % 3 === 0 || undefined} style={{ left: `${(i / 12) * 100}%` }}>
              {monthFmt.format(m)}
            </span>
          ))}
        </div>
        <div className={styles.band}>
          {stage.timeline.map((s, i) => {
            const a = pos(toDate(s.start).getTime());
            const b = pos(toDate(s.end).getTime());
            const isCurrent = s.key === stage.stage;
            return (
              <span key={`${s.key}-${i}`} className={styles.segment} data-current={isCurrent || undefined} data-alt={i % 2 === 1 || undefined}
                style={{ left: `${a}%`, width: `${Math.max(0, b - a)}%` }} title={loc(s.label, locale)}>
              </span>
            );
          })}
          {continues ? <span className={styles.continues}>{t('field.stage.continues')} ›</span> : null}
        </div>
        {nowInWindow ? (
          <div className={styles.nowRow}>
            <span className={styles.now} style={{ left: `${nowPct}%` }}>
              <span className={styles.nowLabel}>{t('actwin.now')}{stage.gdd_cum !== null ? ` · ${formatNumber(stage.gdd_cum, locale)} ${t('units.gdd')}` : ''}</span>
            </span>
          </div>
        ) : null}
      </div>
      <p className={styles.line}>
        {stage.gdd_cum !== null
          ? t('field.stage.now', { stage: current ?? '', gdd: formatNumber(stage.gdd_cum, locale) })
          : t('field.stage.nowNoGdd', { stage: current ?? '' })}
      </p>
      {next && stage.next_stage_expected_on ? (
        <p className={styles.line}>
          {stage.next_stage_plus_minus_days
            ? t('field.stage.nextPm', { stage: next, date: formatDateShort(stage.next_stage_expected_on, locale, now), days: stage.next_stage_plus_minus_days })
            : t('field.stage.next', { stage: next, date: formatDateShort(stage.next_stage_expected_on, locale, now) })}
        </p>
      ) : null}
      {stage.method && stage.method !== 'gdd' ? <p className={styles.meta}>{t('field.stage.method.calendar')}</p> : null}
      {stage.explanation ? <p className={styles.meta}>{loc(stage.explanation, locale)}</p> : null}
      <p className={styles.meta}>{t('field.stage.source')}</p>
    </div>
  );
}
