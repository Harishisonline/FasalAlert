import { BadgeCheck, CloudDrizzle, ClockAlert, ExternalLink, History, Layers2, Store } from '@/components/Icon';
import { SampleTag } from '@/components/UI/Badges';
import type { Translator } from '@/lib/i18n';
import type { Locale } from '@/lib/locales';
import { formatDateTime } from '@/lib/format';
import { isSafeHttpUrl, type SourceItem } from '@/lib/view';
import styles from './SourceLine.module.css';

export interface SourceLineProps {
  sources: SourceItem[];
  t: Translator;
  locale: Locale;
  now: Date;
  /** R1 always adds "IST" (design.md 14.8). */
  ist?: boolean;
  compact?: boolean;
}

function Icon({ item }: { item: SourceItem }) {
  if (item.stale) return <ClockAlert size={16} aria-hidden="true" className={styles.staleIcon} />;
  switch (item.kind) {
    case 'forecast': return <CloudDrizzle size={16} aria-hidden="true" />;
    case 'observed': return <History size={16} aria-hidden="true" />;
    case 'advisory': return <BadgeCheck size={16} aria-hidden="true" className={item.verified ? styles.verifiedIcon : undefined} />;
    case 'market': return <Store size={16} aria-hidden="true" />;
    case 'model': return <Layers2 size={16} aria-hidden="true" />;
    default: return <Layers2 size={16} aria-hidden="true" />;
  }
}

function Line({ item, t, locale, now, ist }: { item: SourceItem } & Omit<SourceLineProps, 'sources'>) {
  const time = item.at ? `${formatDateTime(item.at, locale, now)}${ist ? ' IST' : ''}` : '';
  let text: string;
  if (item.kind === 'synthetic') text = t('state.syntheticSource');
  else if (item.stale && time) text = t('source.stale', { label: item.label, time });
  else if (!time) text = item.label;
  else if (item.kind === 'forecast') text = t('source.forecast', { label: item.label, time });
  else if (item.kind === 'observed') text = t('source.observed', { label: item.label, time });
  else if (item.kind === 'model') text = t('source.model', { label: item.label, time });
  else text = t('source.generic', { label: item.label, time });
  return (
    <span className={styles.item} data-stale={item.stale || undefined}>
      {item.kind === 'synthetic' ? <SampleTag label={t('common.sampleData')} /> : <Icon item={item} />}
      <span className={styles.text}>
        {item.at ? <time dateTime={item.at}>{text}</time> : text}
        {item.kind === 'advisory' && item.verified ? <span className={styles.verified}> · {t('common.verified')}</span> : null}
      </span>
      {isSafeHttpUrl(item.url) ? (
        <a className={styles.link} href={item.url} target="_blank" rel="noopener noreferrer" title={item.url} aria-label={`${t('common.openSource', { label: item.label })} ${t('social.newTab')}`}>
          <ExternalLink size={16} aria-hidden="true" />
        </a>
      ) : null}
    </span>
  );
}

/** Provenance under every number group: source, time, link (PRD §4.3, §14.3). */
export function SourceLine({ sources, t, locale, now, ist, compact }: SourceLineProps) {
  const items = sources.filter((s) => s.label);
  if (items.length === 0) return null;
  return (
    <p className={styles.line} data-compact={compact || undefined}>
      {items.map((s, i) => (
        <span key={`${s.label}-${i}`} className={styles.wrap}>
          {i > 0 ? <span aria-hidden="true" className={styles.sep}>·</span> : null}
          <Line item={s} t={t} locale={locale} now={now} ist={ist} />
        </span>
      ))}
    </p>
  );
}
