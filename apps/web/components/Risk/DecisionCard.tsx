import Link from 'next/link';
import type { ReactNode } from 'react';
import type { Abstention, Crop, Decision, Risk } from '@fasalalert/shared/api';
import { Clock, ClockAlert, CropIcon, History } from '@/components/Icon';
import { Disclosure } from '@/components/UI/Disclosure';
import { StageChip, TodayLabel } from '@/components/UI/Badges';
import { Skeleton, SkeletonLines } from '@/components/Feedback/Skeleton';
import { formatDateTime, formatTemp } from '@/lib/format';
import { cardModel, isAbstention, type CardState } from '@/lib/risk';
import {
  actByText, chancePhrase, cropLabel, fromSourceRef, kindLabel, levelLabel, naturalText, pctText, type SourceItem, type ViewCtx,
} from '@/lib/view';
import { AbstainNotice } from './AbstainNotice';
import { Countdown } from './Countdown';
import { ProbabilityMeter } from './ProbabilityMeter';
import { RiskBadge } from './RiskBadge';
import { SourceLine } from './SourceLine';
import styles from './DecisionCard.module.css';

export interface DecisionCardField { id: number; name: string; crop: Crop; variety?: string | null; stageLabel?: string | null }

export interface DecisionCardProps {
  variant: 'compact' | 'full' | 'offline';
  field: DecisionCardField;
  decision: Decision | Abstention | null;
  /** Force a state: 'raw' when the decision engine is down, 'loading' for skeletons. */
  state?: Extract<CardState, 'raw' | 'loading'>;
  rawRisks?: Risk[];
  pinned?: boolean;
  ctx: ViewCtx;
  href?: string;
  /** When the data on screen was fetched, for the offline "Last known" label (PRD AC 22). */
  renderedAt?: string;
  /** Full variant: compact TemperatureBand and ActionWindow (design.md 14.1, fix 1). */
  extra?: ReactNode;
  abstainAction?: ReactNode;
  headingLevel?: 2 | 3;
  /** Last update time when the API reported data_stale for every field. */
  staleSince?: string | null;
}

function firstSentence(text: string): string {
  const m = text.match(/^(.+?[.!?।])(\s|$)/u);
  return m?.[1] ?? text;
}

function riskSources(decision: Decision, risk: Risk | null): SourceItem[] {
  const items: SourceItem[] = [];
  const ev = risk?.evidence;
  if (ev?.forecast_source) items.push({ label: String(ev.forecast_source), at: ev.forecast_fetched_at ?? null, kind: 'forecast' });
  if (decision.advisory) items.push({ label: decision.advisory.institution, url: decision.advisory.source_url, kind: 'advisory', verified: decision.advisory.verified });
  if (items.length === 0) for (const s of decision.sources.slice(0, 2)) items.push(fromSourceRef(s));
  return items;
}

export function DecisionCard(props: DecisionCardProps) {
  const { variant, field, decision, ctx, pinned, href, renderedAt, extra, abstainAction, headingLevel = 3 } = props;
  const { t, locale, now, unit } = ctx;
  const H = `h${headingLevel}` as 'h2' | 'h3';
  const headingId = `dc-${variant}-${field.id}`;
  const descId = `${headingId}-d`;

  if (props.state === 'loading') {
    return (
      <div className={styles.card} data-state="loading" aria-busy="true">
        <span className="visually-hidden">{t('state.loading')}</span>
        <Skeleton height={28} width="40%" radius="full" />
        <Skeleton height="1.4em" width="60%" />
        <SkeletonLines lines={3} />
        <Skeleton height={48} width="50%" />
      </div>
    );
  }

  const base = props.state === 'raw' ? { state: 'raw' as const, level: 'nodata' as const, risk: null, lastUpdatedAt: null } : cardModel(decision, now);
  const model = !decision && props.staleSince ? { ...base, lastUpdatedAt: props.staleSince } : base;
  const state = model.state;
  const linked = variant !== 'full' && href;
  const spine = state === 'actionable' || state === 'no-risk' ? 'risk' : state === 'abstain' ? 'abstain' : state === 'stale' ? 'stale' : 'raw';
  const lastKnown = variant === 'offline' || renderedAt;

  const title = (
    <div className={styles.titleRow}>
      <CropIcon crop={field.crop} size={24} />
      <H id={headingId} className={styles.fieldName}>
        {linked ? <Link href={href} className={styles.stretched}>{field.name}</Link> : field.name}
      </H>
      {field.stageLabel ? <StageChip>{field.stageLabel}</StageChip> : null}
    </div>
  );

  let body: ReactNode = null;
  let description = '';
  const risk = model.risk;
  const d = decision && !isAbstention(decision) ? decision : null;

  if (state === 'actionable' && d && risk) {
    const action = variant === 'full' ? d.action_text : firstSentence(d.action_text);
    const actBy = d.action_by ? actByText(t, d.action_by, now, locale) : null;
    description = t('decision.aria', { field: field.name, level: levelLabel(t, risk.level), kind: kindLabel(t, risk.kind), action, actBy: actBy ?? '' });
    body = (
      <>
        {variant === 'full' ? <p className={styles.headline}>{d.headline}</p> : null}
        <p className={styles.action}>{action}</p>
        {actBy ? (
          <p className={styles.actBy}>
            <Clock size={20} aria-hidden="true" />
            <span>{actBy}</span>
            {d.action_by ? <Countdown target={d.action_by} initialNow={now.toISOString()} className={styles.countdown} /> : null}
          </p>
        ) : null}
        {variant === 'full' ? (
          <div className={styles.fullGrid}>
            <ProbabilityMeter label={t(`chance.meterLabel.${risk.kind}`)} value={risk.probability} level={risk.level} variant="full" t={t} locale={locale} />
            {extra}
            {d.advisory ? (
              <figure className={styles.advisory}>
                <blockquote className={styles.quote}>{d.advisory.text}</blockquote>
                <figcaption>
                  <SourceLine
                    sources={[{ label: [d.advisory.source, d.advisory.year].filter(Boolean).join(', '), url: d.advisory.source_url, kind: 'advisory', verified: d.advisory.verified }]}
                    t={t} locale={locale} now={now}
                  />
                </figcaption>
              </figure>
            ) : null}
          </div>
        ) : (
          <p className={styles.chance}>{chancePhrase(t, risk.kind, risk.probability, risk.window_start ?? d.action_by, now, locale)}</p>
        )}
        <SourceLine sources={riskSources(d, risk)} t={t} locale={locale} now={now} compact />
        {variant !== 'full' ? (
          <Disclosure label={t('common.whyThis')} className={styles.why}>
            <ul className={styles.whyList}>
              {typeof risk.tmin_c === 'number' ? (
                <li>
                  {t('decision.why.forecast', { value: formatTemp(risk.tmin_c, locale, unit) })}
                  {typeof risk.band_low_c === 'number' && typeof risk.band_high_c === 'number'
                    ? ` (${t('decision.why.range', { low: formatTemp(risk.band_low_c, locale, unit), high: formatTemp(risk.band_high_c, locale, unit) })})`
                    : ''}
                </li>
              ) : null}
              {typeof risk.threshold_c === 'number' ? <li>{t('decision.why.threshold', { value: formatTemp(risk.threshold_c, locale, unit) })}</li> : null}
              <li>{t('decision.why.chance', { pct: pctText(t, risk.probability, locale), natural: naturalText(t, risk.probability) })}</li>
            </ul>
            <ProbabilityMeter label={t(`chance.meterLabel.${risk.kind}`)} value={risk.probability} level={risk.level} variant="compact" t={t} locale={locale} />
            {href ? <Link href={href} className={styles.fullLink}>{t('common.seeFullDetails')}</Link> : null}
          </Disclosure>
        ) : null}
      </>
    );
  } else if (state === 'no-risk' && d) {
    description = t('decision.ariaNoRisk', { field: field.name });
    body = (
      <>
        <p className={styles.noRisk}>{t('decision.noRisk', { crop: cropLabel(t, field.crop, true) })}</p>
        <SourceLine sources={riskSources(d, model.risk)} t={t} locale={locale} now={now} compact />
      </>
    );
  } else if (state === 'abstain' && decision && isAbstention(decision)) {
    description = t('decision.ariaAbstain', { field: field.name, title: t(`abstain.${decision.abstain_reason}.title`) });
    body = (
      <AbstainNotice reason={decision.abstain_reason} kvk={decision.kvk} lastUpdatedAt={decision.last_update} variant={variant === 'full' ? 'full' : 'compact'}
        action={abstainAction} t={t} locale={locale} now={now} />
    );
  } else if (state === 'stale') {
    description = t('decision.ariaStale', { field: field.name });
    body = (
      <p className={styles.stale}>
        <ClockAlert size={20} aria-hidden="true" />
        <span>{model.lastUpdatedAt ? t('state.stale.card', { time: formatDateTime(model.lastUpdatedAt, locale, now) }) : t('state.stale.cardNoTime')}</span>
      </p>
    );
  } else {
    // Raw model outputs without a recommendation (PRD §7.3, decision engine down).
    const raws = props.rawRisks ?? decision?.risks ?? [];
    description = t('decision.ariaStale', { field: field.name });
    body = raws.length ? (
      <ul className={styles.rawList}>
        {raws.map((r, i) => (
          <li key={`${r.kind}-${i}`}>
            <span className={styles.rawKind}>{kindLabel(t, r.kind)}: </span>
            {typeof r.tmin_c === 'number' ? `${t(r.kind === 'heatwave' ? 'decision.raw.tmax' : 'decision.raw.tmin', { value: formatTemp(r.tmin_c, locale, unit) })} ` : ''}
            {typeof r.threshold_c === 'number' ? `${t('decision.raw.threshold', { value: formatTemp(r.threshold_c, locale, unit) })} ` : ''}
            {t('decision.raw.chance', { kind: kindLabel(t, r.kind).toLowerCase(), pct: pctText(t, r.probability, locale) })}
            <SourceLine sources={[{ label: r.model_version, kind: 'model', at: r.evidence?.forecast_fetched_at ?? null }]} t={t} locale={locale} now={now} compact />
          </li>
        ))}
      </ul>
    ) : <p className={styles.noRisk}>{t('decision.raw.none')}</p>;
  }

  const badgeLevel = state === 'actionable' || state === 'no-risk' ? model.level : null;

  return (
    <article
      className={styles.card}
      data-spine={spine}
      data-level={badgeLevel ?? undefined}
      data-pinned={pinned || undefined}
      data-variant={variant}
      data-linked={linked || undefined}
      aria-labelledby={headingId}
      aria-describedby={descId}
    >
      <span id={descId} className="visually-hidden">{pinned ? `${t('decision.urgent')}. ` : ''}{description}</span>
      <div className={styles.top}>
        {pinned ? <TodayLabel label={t('decision.today')} /> : null}
        {badgeLevel && risk ? <RiskBadge level={badgeLevel} kind={badgeLevel === 'none' ? undefined : risk.kind} t={t} /> : badgeLevel === 'none' ? <RiskBadge level="none" t={t} /> : null}
        {variant === 'full' && model.lastUpdatedAt ? <span className={styles.updated}>{t('decision.updated', { time: formatDateTime(model.lastUpdatedAt, locale, now) })}</span> : null}
      </div>
      {variant !== 'full' ? title : null}
      <div className={styles.body}>{body}</div>
      {lastKnown ? (
        <p className={styles.lastKnown} {...(variant === 'offline' ? {} : { 'data-offline-only': '' })}>
          <History size={16} aria-hidden="true" />
          {t('state.lastKnown', { time: formatDateTime(renderedAt ?? now.toISOString(), locale, now) })}
        </p>
      ) : null}
    </article>
  );
}
