import type { RiskKind, RiskLevel } from '@fasalalert/shared/api';
import { KindIcon } from '@/components/Icon';
import type { Translator } from '@/lib/i18n';
import type { Locale } from '@/lib/locales';
import { countdown, formatTime, toDate } from '@/lib/format';
import { kindLabel } from '@/lib/view';
import styles from './ActionWindow.module.css';

export interface ActionWindowProps {
  actionBy: string | null | undefined;
  windowStart?: string | null;
  windowEnd?: string | null;
  /** Only when the API supplies a close time (Appendix B, Q5). */
  closesAt?: string | null;
  kind: RiskKind;
  level: RiskLevel;
  compact?: boolean;
  t: Translator;
  locale: Locale;
  now: Date;
}

/** The action window as a real timeline (PRD §7.4, design.md 14.7). */
export function ActionWindow({ actionBy, windowStart, windowEnd, closesAt, kind, level, compact, t, locale, now }: ActionWindowProps) {
  if (!actionBy || level === 'none') return null;
  const nowMs = now.getTime();
  const actMs = toDate(actionBy).getTime();
  const startMs = windowStart ? toDate(windowStart).getTime() : null;
  const endMs = windowEnd ? toDate(windowEnd).getTime() : null;
  const closeMs = closesAt ? toDate(closesAt).getTime() : null;
  const from = Math.min(nowMs, actMs);
  const to = Math.max(endMs ?? startMs ?? actMs, actMs, closeMs ?? 0, nowMs) || actMs;
  const span = Math.max(1, to - from);
  const pct = (ms: number) => `${(((ms - from) / span) * 100).toFixed(2)}%`;
  const width = (a: number, b: number) => `${((Math.max(0, b - a) / span) * 100).toFixed(2)}%`;
  const passed = nowMs > actMs;
  const tooLateFrom = closeMs ?? actMs;
  const c = countdown(actionBy, now);

  const items: string[] = [t('actwin.listNow', { time: formatTime(now, locale) }), t('actwin.listActBy', { time: formatTime(actionBy, locale) })];
  if (closesAt) items.push(t('actwin.listCloses', { time: formatTime(closesAt, locale) }));
  if (windowStart && windowEnd) items.push(t('actwin.listRisk', { kind: kindLabel(t, kind), start: formatTime(windowStart, locale), end: formatTime(windowEnd, locale) }));

  return (
    <div className={styles.window} data-compact={compact || undefined} data-passed={passed || undefined}>
      <ol className="visually-hidden">
        {items.map((s) => <li key={s}>{s}</li>)}
      </ol>
      <div className={styles.visual} aria-hidden="true">
        <div className={styles.markers}>
          <span className={styles.marker} style={{ left: pct(nowMs) }} data-edge="start">
            <span className={styles.time}>{formatTime(now, locale)}</span>
            <span className={styles.name}>{t('actwin.now')}</span>
          </span>
          <span className={styles.marker} style={{ left: pct(actMs) }} data-alt>
            <span className={styles.time}>{formatTime(actionBy, locale)}</span>
            <span className={styles.name}>{t('actwin.actBy')}</span>
          </span>
          {windowStart && startMs !== null ? (
            <span className={styles.marker} style={{ left: pct(startMs) }} data-edge="end">
              <span className={styles.time}>{formatTime(windowStart, locale)}{windowEnd ? ` - ${formatTime(windowEnd, locale)}` : ''}</span>
              <span className={styles.name}><KindIcon kind={kind} size={16} /> {kindLabel(t, kind)}</span>
            </span>
          ) : null}
        </div>
        <div className={styles.bar}>
          {!passed ? <span className={styles.seg} data-seg="best" style={{ left: pct(nowMs), width: width(nowMs, actMs) }} /> : null}
          {closeMs !== null ? <span className={styles.seg} data-seg="helps" style={{ left: pct(actMs), width: width(actMs, closeMs) }} /> : null}
          {startMs !== null ? <span className={styles.seg} data-seg="late" style={{ left: pct(Math.max(tooLateFrom, nowMs)), width: width(Math.max(tooLateFrom, nowMs), startMs) }} /> : null}
          {startMs !== null && endMs !== null ? <span className={styles.seg} data-seg="risk" data-level={level} style={{ left: pct(startMs), width: width(startMs, endMs) }} /> : null}
        </div>
        {!compact ? (
          <div className={styles.legend}>
            <span data-seg="best">{t('actwin.best')}</span>
            {closeMs !== null ? <span data-seg="helps">{t('actwin.stillHelps')}</span> : null}
            <span data-seg="late">{t('actwin.tooLate')}</span>
            <span data-seg="risk" data-level={level}>{t('actwin.riskSeg')}</span>
          </div>
        ) : null}
      </div>
      {passed ? <p className={styles.passed}>{t('decision.passed')}</p> : c.totalMinutes < 12 * 60 ? (
        <p className={styles.left}>{c.hours > 0 ? t('time.leftToAct', { h: c.hours, m: c.minutes }) : t('time.leftToActMinutes', { m: c.minutes })}</p>
      ) : null}
    </div>
  );
}
