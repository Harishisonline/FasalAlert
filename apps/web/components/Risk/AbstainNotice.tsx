import type { ReactNode } from 'react';
import type { AbstainReason } from '@fasalalert/shared/api';
import { CircleHelp, Phone } from '@/components/Icon';
import { ButtonLink } from '@/components/UI/Button';
import type { Translator } from '@/lib/i18n';
import type { Locale } from '@/lib/locales';
import { KISAN_CALL_CENTRE } from '@/lib/config';
import { formatDateTime, spellDigits, telHref } from '@/lib/format';
import styles from './AbstainNotice.module.css';

export interface AbstainNoticeProps {
  reason: AbstainReason;
  kvk?: { name: string; phone: string } | null;
  lastUpdatedAt?: string | null;
  /** The next step (e.g. "Add sowing date", quick prompts, Try again). */
  action?: ReactNode;
  variant?: 'compact' | 'full';
  t: Translator;
  locale: Locale;
  now: Date;
  headingLevel?: 2 | 3;
}

/** The honest "I do not know": amber, never red (PRD §14.3, design.md 14.9). */
export function AbstainNotice({ reason, kvk, lastUpdatedAt, action, variant = 'full', t, locale, now, headingLevel = 3 }: AbstainNoticeProps) {
  const H = `h${headingLevel}` as 'h2' | 'h3';
  const reasonText = reason === 'data_stale'
    ? (lastUpdatedAt ? t('abstain.data_stale.reason', { time: formatDateTime(lastUpdatedAt, locale, now) }) : t('abstain.data_stale.reasonNoTime'))
    : t(`abstain.${reason}.reason`);
  const showCall = reason === 'no_retrieval_above_threshold' || reason === 'model_confidence_below_threshold' || variant === 'full';
  const contact = kvk ?? { name: t('abstain.kcc'), phone: KISAN_CALL_CENTRE };
  return (
    <div className={styles.notice} data-variant={variant} role="status">
      <CircleHelp size={24} aria-hidden="true" className={styles.icon} />
      <div className={styles.body}>
        <H className={styles.title}>{t(`abstain.${reason}.title`)}</H>
        <p className={styles.reason}>{reasonText}</p>
        {action ? <div className={styles.action}>{action}</div> : null}
        {showCall && reason !== 'outside_domain' && reason !== 'missing_field_input' ? (
          <div className={styles.contact}>
            <span className={styles.kvk}><span>{contact.name}</span> <span className="tabular" lang="en">{contact.phone}</span></span>
            <ButtonLink
              href={telHref(contact.phone)}
              variant="call"
              icon={<Phone size={20} aria-hidden="true" />}
              aria-label={t('common.callNamed', { name: contact.name, digits: spellDigits(contact.phone) })}
            >
              {t('common.call')}
            </ButtonLink>
          </div>
        ) : null}
      </div>
    </div>
  );
}
