'use client';
import Link from 'next/link';
import { useId, useState } from 'react';
import type { Alert, AlertDelivery } from '@fasalalert/shared/api';
import { Bell, Check, CheckCheck, ChevronDown, CircleX, Clock, KindIcon, MessageSquare } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { FeedbackButton } from '@/components/Field/FeedbackButton';
import { ActionWindow } from '@/components/Risk/ActionWindow';
import { RiskBadge } from '@/components/Risk/RiskBadge';
import { SourceLine } from '@/components/Risk/SourceLine';
import { formatDateTime, formatTemp, formatTime } from '@/lib/format';
import { riskKindOf } from '@/lib/risk';
import { kindLabel, pctText } from '@/lib/view';
import styles from './AlertCard.module.css';

function latestDelivery(a: Alert): AlertDelivery | null {
  return [...(a.deliveries ?? [])].sort((x, y) => y.created_at.localeCompare(x.created_at))[0] ?? null;
}

/** One sent alert (PRD §7.6, design.md 14.19). Expanding does not mark it read (D-14). */
export function AlertCard({ alert, onMarkRead, defaultOpen, unit }: { alert: Alert; onMarkRead: (id: number) => Promise<boolean>; defaultOpen?: boolean; unit: 'celsius' | 'fahrenheit' }) {
  const { t, locale } = useI18n();
  const id = useId();
  const now = new Date();
  const [open, setOpen] = useState(Boolean(defaultOpen));
  const [marking, setMarking] = useState(false);
  const [markError, setMarkError] = useState(false);
  const unread = !alert.read_at;
  const kind = riskKindOf(alert.kind);
  const d = latestDelivery(alert);
  const channel = alert.channel?.toLowerCase();
  const channelLabel = channel === 'sms' ? t('alerts.channel.sms') : channel === 'whatsapp' ? t('alerts.channel.whatsapp') : channel === 'push' ? t('alerts.channel.push') : alert.channel;
  const queued = d?.status === 'queued' || (!alert.sent_at && alert.queued_until);
  const statusText = alert.read_at ? t('alerts.status.read', { time: formatDateTime(alert.read_at, locale, now) })
    : queued ? (alert.queued_until ? t('alerts.status.queued', { time: formatTime(alert.queued_until, locale) }) : t('alerts.status.queuedNoTime'))
      : d?.status === 'failed' ? t('alerts.status.failed')
        // The dev outbox is a file on the server: never call that "sent" (docs/UX_QA_AUDIT.md ALR-01).
        : d?.provider === 'dev-outbox' ? t('alerts.status.devOutbox') : t('alerts.status.sent');
  const StatusIcon = alert.read_at ? CheckCheck : queued ? Clock : d?.status === 'failed' ? CircleX : Check;
  const ChannelIcon = channel === 'push' ? Bell : MessageSquare;
  const sentAt = alert.sent_at ?? alert.created_at;
  const risk = alert.detail?.risk ?? null;
  const advisory = alert.detail?.advisory ?? null;
  const summary = alert.message.split('\n')[0];

  const mark = async () => {
    setMarking(true);
    setMarkError(false);
    const ok = await onMarkRead(alert.id);
    setMarking(false);
    if (!ok) setMarkError(true);
  };

  return (
    <article className={styles.card} data-level={alert.level} data-unread={unread || undefined} data-status={queued ? 'queued' : d?.status} id={`alert-${alert.id}`}>
      <div className={styles.head}>
        <button type="button" className={styles.toggle} aria-expanded={open} aria-controls={`${id}-body`} onClick={() => setOpen(!open)}>
          {unread ? <span className={styles.dot} aria-hidden="true" /> : <span className={styles.dotSpace} aria-hidden="true" />}
          {kind ? <KindIcon kind={kind} size={32} className={styles.kindIcon} /> : null}
          <span className={styles.main}>
            {unread ? <span className="visually-hidden">{t('alerts.unreadHidden')}. </span> : null}
            <span className={styles.badgeRow}><RiskBadge level={alert.level} kind={kind ?? undefined} size="sm" t={t} /></span>
            <span className={styles.summary}>{summary}</span>
            {alert.field_name ? <span className={styles.field}>{alert.field_name}</span> : null}
            <span className={styles.meta}>
              <time dateTime={sentAt}>{formatDateTime(sentAt, locale, now)}</time>
              <span aria-hidden="true">·</span>
              <ChannelIcon size={16} aria-hidden="true" /> <span>{channelLabel}</span>
              <span aria-hidden="true">·</span>
              <StatusIcon size={16} aria-hidden="true" /> <span data-tone={d?.status === 'failed' ? 'danger' : undefined}>{statusText}</span>
            </span>
          </span>
          <ChevronDown size={24} aria-hidden="true" className={styles.chevron} data-open={open || undefined} />
          <span className="visually-hidden">{t('alerts.expand')}</span>
        </button>
        {unread && !open ? (
          <button type="button" className={styles.quickRead} onClick={() => void mark()} disabled={marking}>{t('alerts.markReadShort')}</button>
        ) : null}
      </div>
      {markError && !open ? <p className={styles.error} role="alert">{t('alerts.markReadFailed')}</p> : null}
      <div id={`${id}-body`} className={styles.body} hidden={!open}>
        <p className={styles.label}>{t('alerts.messageSent')}</p>
        <blockquote className={styles.quote}>{alert.message}</blockquote>
        {advisory ? (
          <div>
            <p className={styles.label}>{t('alerts.advisory')}</p>
            <blockquote className={styles.quote}>{advisory.text}</blockquote>
            <SourceLine sources={[{ label: [advisory.source, advisory.year].filter(Boolean).join(', '), url: advisory.source_url, kind: 'advisory', verified: advisory.verified }]} t={t} locale={locale} now={now} />
          </div>
        ) : null}
        {risk ? (
          <div>
            <p className={styles.label}>{t('alerts.model')}</p>
            <p className="tabular">
              {typeof risk.tmin_c === 'number' && typeof risk.threshold_c === 'number'
                ? t('alerts.modelLine', {
                  value: formatTemp(risk.tmin_c, locale, unit),
                  low: typeof risk.band_low_c === 'number' ? formatTemp(risk.band_low_c, locale, unit) : '',
                  high: typeof risk.band_high_c === 'number' ? formatTemp(risk.band_high_c, locale, unit) : '',
                  threshold: formatTemp(risk.threshold_c, locale, unit), pct: pctText(t, risk.probability, locale),
                })
                : t('alerts.modelLineShort', { kind: kindLabel(t, risk.kind), pct: pctText(t, risk.probability, locale) })}
            </p>
            <SourceLine sources={[{ label: risk.model_version, kind: 'model', at: risk.evidence?.forecast_fetched_at ?? null }]} t={t} locale={locale} now={now} compact />
            <ActionWindow actionBy={alert.detail?.action_by ?? null} windowStart={risk.window_start} windowEnd={risk.window_end} kind={risk.kind} level={risk.level} compact t={t} locale={locale} now={now} />
          </div>
        ) : null}
        <div className={styles.actions}>
          {unread ? <button type="button" className={styles.primary} onClick={() => void mark()} disabled={marking}>{t('alerts.markRead')}</button> : null}
          {alert.field_id ? <Link href={`/${locale}/field/${alert.field_id}`} className={styles.secondary}>{t('alerts.openField')}</Link> : null}
          <FeedbackButton alertId={alert.id} initial={alert.feedback} />
        </div>
        {markError ? <p className={styles.error} role="alert">{t('alerts.markReadFailed')}</p> : null}
      </div>
    </article>
  );
}
