import { LevelIcon } from '@/components/Icon';
import type { Translator } from '@/lib/i18n';
import type { DisplayLevel } from '@/lib/risk';
import styles from './MapLegend.module.css';

const ORDER: DisplayLevel[] = ['none', 'low', 'medium', 'high', 'critical', 'nodata'];

/** Real HTML legend: icon, label and pattern swatch for each level (design.md 16.9). */
export function MapLegend({ t, className }: { t: Translator; className?: string }) {
  return (
    <div className={[styles.legend, className ?? ''].join(' ')}>
      <h2 className="visually-hidden">{t('board.legend')}</h2>
      <ul className={styles.list}>
        {ORDER.map((level) => (
          <li key={level} className={styles.item}>
            <span className={styles.swatch} data-level={level} aria-hidden="true" />
            <LevelIcon level={level} size={20} className={styles.icon} />
            <span>{t(`risk.level.${level}`)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
