import type { Decision } from '@fasalalert/shared/api';
import { CalendarCheck, Hourglass, Store, TriangleAlert } from '@/components/Icon';
import { formatDateShort } from '@/lib/format';
import type { ViewCtx } from '@/lib/view';
import styles from './RecommendationBand.module.css';

export type RecommendationVariant = 'agree' | 'caution' | 'price-only' | 'unavailable';

/** The payoff of R7: harvest when, sell where, hold or sell (PRD §7.7, design.md 14.15). */
export function RecommendationBand({ recommendation, variant, ctx, reason, headingLevel = 2 }: {
  recommendation: Decision['recommendation']; variant: RecommendationVariant; ctx: ViewCtx; reason?: string; headingLevel?: 2 | 3;
}) {
  const { t, locale, now } = ctx;
  const H = `h${headingLevel}` as 'h2' | 'h3';
  if (!recommendation || variant === 'unavailable') {
    return (
      <section className={styles.band} data-variant="unavailable" aria-labelledby="rec-h">
        <H id="rec-h" className={styles.title}>{t('market.rec.title')}</H>
        <p>{reason ? t('market.rec.unavailableReason', { reason }) : t('market.rec.unavailable')}</p>
      </section>
    );
  }
  const r = recommendation;
  return (
    <section className={styles.band} data-variant={variant} aria-labelledby="rec-h">
      <H id="rec-h" className={styles.title}>{t('market.rec.title')}</H>
      <dl className={styles.slots}>
        <div className={styles.slot}>
          <dt><CalendarCheck size={24} aria-hidden="true" /> {t('market.rec.harvest')}</dt>
          <dd>{r.harvest_on ? formatDateShort(r.harvest_on, locale, now) : t('market.rec.notSet')}</dd>
        </div>
        <div className={styles.slot}>
          <dt><Store size={24} aria-hidden="true" /> {t('market.rec.sellAt')}</dt>
          <dd>{r.sell_at ?? t('market.rec.notSet')}</dd>
        </div>
        <div className={styles.slot}>
          <dt><Hourglass size={24} aria-hidden="true" /> {r.hold_until ? t('market.rec.holdUntil') : t('market.rec.sellNow')}</dt>
          <dd>{r.hold_until ? formatDateShort(r.hold_until, locale, now) : t('market.rec.sellNow')}</dd>
        </div>
      </dl>
      <p className={styles.reason}>
        {variant === 'caution' ? <TriangleAlert size={20} aria-hidden="true" className={styles.caution} /> : null}
        <span>{r.net_reason}</span>
      </p>
      {variant === 'price-only' ? <p className={styles.note}>{t('market.rec.priceOnly')}</p> : null}
    </section>
  );
}
