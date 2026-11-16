'use client';
import { useState } from 'react';
import { useMediaQuery } from '@/lib/hooks';
import type { Preferences } from '@fasalalert/shared/api';
import { useI18n } from '@/components/I18n';
import { Disclosure } from '@/components/UI/Disclosure';
import { DeliverySettings, quietRange } from './DeliverySettings';
import styles from './DeliveryCard.module.css';

/** "How you get alerts": collapsed summary on mobile, the open card in the desktop rail (design.md 12.6). */
export function DeliveryCard({ prefs }: { prefs: Preferences }) {
  const { t } = useI18n();
  const desktop = useMediaQuery('(min-width: 1024px)');
  const [current, setCurrent] = useState(prefs);
  const parts = (['sms', 'whatsapp', 'push'] as const)
    .filter((c) => c !== 'whatsapp' || current.channel_availability.whatsapp)
    .map((c) => t(current.channels[c] ? 'delivery.summaryOn' : 'delivery.summaryOff', { channel: t(`delivery.${c}`) }));
  const q = quietRange(t as never, current.quiet_hours_start, current.quiet_hours_end);
  if (q) parts.push(t('delivery.summaryQuiet', { range: q }));
  return (
    <section className={styles.card} aria-labelledby="delivery-h">
      <h2 id="delivery-h" className={styles.title}>{t('delivery.title')}</h2>
      <Disclosure label={<span className={styles.summary}>{parts.join(' · ')}</span>} defaultOpen={desktop} key={desktop ? 'd' : 'm'}>
        <DeliverySettings initial={current} onChange={setCurrent} />
      </Disclosure>
    </section>
  );
}
