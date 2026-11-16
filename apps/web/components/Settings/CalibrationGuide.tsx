import { Info } from '@/components/Icon';
import { Disclosure } from '@/components/UI/Disclosure';
import type { Translator } from '@/lib/i18n';
import styles from './CalibrationGuide.module.css';

/**
 * What calibration changes, why a farmer might change it, the allowed range, the default and its status
 * (docs/UX_QA_AUDIT.md CAL-01). Ranges are the API's validation limits (schemas/bodies.py CalibrationPatchBody).
 */
export function CalibrationGuide({ t }: { t: Translator }) {
  const rows: [string, string][] = [
    ['calib.guide.sensitivity', 'calib.guide.sensitivityBody'],
    ['calib.guide.limits', 'calib.guide.limitsBody'],
    ['calib.guide.lead', 'calib.guide.leadBody'],
    ['calib.guide.status', 'calib.guide.statusBody'],
    ['calib.guide.effect', 'calib.guide.effectBody'],
  ];
  return (
    <section className={styles.guide} aria-labelledby="calib-guide">
      <h2 id="calib-guide" className={styles.title}><Info size={20} aria-hidden="true" /> {t('calib.guide.title')}</h2>
      <p>{t('calib.guide.intro')}</p>
      <Disclosure label={t('calib.guide.more')}>
        <dl className={styles.list}>
          {rows.map(([k, v]) => (<div key={k}><dt>{t(k)}</dt><dd>{t(v)}</dd></div>))}
        </dl>
      </Disclosure>
    </section>
  );
}
