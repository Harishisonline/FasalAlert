import type { RiskLevel } from '@fasalalert/shared/api';
import type { Translator } from '@/lib/i18n';
import type { Locale } from '@/lib/locales';
import { naturalFrequency } from '@/lib/format';
import { naturalText, pctText, termText } from '@/lib/view';
import styles from './ProbabilityMeter.module.css';

export interface ProbabilityMeterProps {
  label: string;
  value: number | null;
  level: RiskLevel;
  /** Only drawn when the API returns an interval. Never synthesised (design.md 14.3, Appendix B Q26). */
  interval?: { low: number; high: number } | null;
  variant?: 'compact' | 'full';
  t: Translator;
  locale: Locale;
}

/** A 10-cell icon array plus a solid mark at the exact value (design.md 14.3, D-5). */
export function ProbabilityMeter({ label, value, level, interval, variant = 'full', t, locale }: ProbabilityMeterProps) {
  if (value === null || !Number.isFinite(value)) {
    return (
      <div className={styles.meter} data-state="unavailable">
        <p className={styles.label}>{label}</p>
        <div className={styles.unavailableTrack} aria-hidden="true" />
        <p className={styles.text}>{t('prob.unavailable')}</p>
      </div>
    );
  }
  const p = Math.min(1, Math.max(0, value));
  const filled = naturalFrequency(p);
  const pct = pctText(t, p, locale);
  const natural = naturalText(t, p);
  const term = termText(t, p);
  return (
    <div className={styles.meter} data-variant={variant} data-level={level} role="img" aria-label={t('prob.meterAria', { label, pct, natural, term })}>
      <div className={styles.head} aria-hidden="true">
        <span className={styles.label}>{label}</span>
        <span className={styles.pct}>{pct}</span>
      </div>
      <div className={styles.trackWrap} aria-hidden="true">
        {interval ? (
          <span className={styles.band} style={{ left: `${interval.low * 100}%`, width: `${Math.max(0, interval.high - interval.low) * 100}%` }} />
        ) : null}
        <div className={styles.track}>
          {Array.from({ length: 10 }, (_, i) => <span key={i} className={styles.cell} data-filled={i < filled || undefined} />)}
        </div>
        <span className={styles.mark} style={{ left: `${p * 100}%` }} />
      </div>
      {variant === 'full' ? (
        <div className={styles.scale} aria-hidden="true">
          <span>{t('prob.unlikely')}</span><span>{t('prob.likely')}</span><span>{t('prob.veryLikely')}</span><span>{t('prob.mostLikely')}</span>
        </div>
      ) : null}
      <p className={styles.text} aria-hidden="true">{t('prob.textLine', { natural: natural.charAt(0).toUpperCase() + natural.slice(1), term })}</p>
    </div>
  );
}
