import type { RiskKind } from '@fasalalert/shared/api';
import { KindIcon, LevelIcon } from '@/components/Icon';
import type { Translator } from '@/lib/i18n';
import type { DisplayLevel } from '@/lib/risk';
import { kindLabel, levelLabel } from '@/lib/view';
import styles from './RiskBadge.module.css';

export interface RiskBadgeProps {
  level: DisplayLevel;
  kind?: RiskKind | 'price';
  size?: 'sm' | 'md' | 'lg';
  /** IMD action wording, lg only (design.md 14.2). */
  showAction?: boolean;
  t: Translator;
}

/** Risk level by icon, word and colour together (PRD §14.5). Not interactive. */
export function RiskBadge({ level, kind, size = 'md', showAction = false, t }: RiskBadgeProps) {
  return (
    <span className={styles.badge} data-level={level} data-size={size}>
      <span className="visually-hidden">{t('risk.prefix')} </span>
      <span className={styles.row}>
        <LevelIcon level={level} size={size === 'lg' ? 24 : 20} />
        <span className={styles.level}>{levelLabel(t, level)}</span>
        {kind ? (
          <>
            <span aria-hidden="true" className={styles.dot}>·</span>
            <span className="visually-hidden">, </span>
            <KindIcon kind={kind} size={size === 'lg' ? 24 : 20} />
            <span className={styles.kind}>{kindLabel(t, kind)}</span>
          </>
        ) : null}
      </span>
      {showAction && size === 'lg' && level !== 'nodata' ? <span className={styles.action}>{t(`risk.action.${level}`)}</span> : null}
    </span>
  );
}
