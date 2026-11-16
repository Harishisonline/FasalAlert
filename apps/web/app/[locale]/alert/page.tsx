import type { Metadata } from 'next';
import { Suspense } from 'react';
import { AlertsClient } from '@/components/Alert/AlertsClient';
import { DeliveryCard } from '@/components/Alert/DeliveryCard';
import { RouteError } from '@/components/Feedback/RouteError';
import { RetryButton } from '@/components/Feedback/RetryButton';
import { PageMain } from '@/components/Layout/Page';
import { PageHeader } from '@/components/Nav/PageHeader';
import { RiskBadge } from '@/components/Risk/RiskBadge';
import { getAlerts, getDecisionsToday, getFields, getMe, redirectIfUnauthenticated } from '@/lib/api';
import { createTranslator, type Translator } from '@/lib/i18n';
import { isLocale, type Locale } from '@/lib/locales';
import { cardModel } from '@/lib/risk';
import styles from './alert.module.css';

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  return { title: createTranslator(isLocale(locale) ? locale : 'mr')('alerts.title') };
}

/** R6 Alerts: what was sent, on which channel, when, and whether it was opened (PRD §7.6). */
export default async function AlertPage({ params, searchParams }: { params: Promise<{ locale: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const locale = (await params).locale as Locale;
  const sp = await searchParams;
  const t = createTranslator(locale);
  const now = new Date();
  const [alerts, me] = await Promise.all([getAlerts(), getMe()]);
  await redirectIfUnauthenticated(alerts, locale);
  const unread = alerts.ok ? alerts.data.unread : 0;
  const focus = typeof sp.focus === 'string' && /^\d+$/.test(sp.focus) ? Number(sp.focus) : null;
  const unit = me.ok ? me.data.temp_unit : 'celsius';


  return (
    <PageMain renderedAt={now.toISOString()}>
        <PageHeader title={t('alerts.title')} description={t('alerts.description')}
          meta={unread > 0 ? <span className={styles.unreadPill}>{t('alerts.unread', { count: unread })}</span> : <span>{t('alerts.allRead')}</span>} />
        <div className={styles.layout}>
          <div className={styles.rail}>
            {me.ok ? <DeliveryCard prefs={me.data.preferences} /> : <RouteError message={t('delivery.loadError')} />}
          </div>
          <div className={styles.list}>
            {!alerts.ok ? (
              <RouteError variant="section" message={t('alerts.loadError')} code={alerts.error?.trace_id} codeLabel={alerts.error?.trace_id ? t('state.errorCode', { code: alerts.error.trace_id }) : undefined} action={<RetryButton />} />
            ) : alerts.data.alerts.length === 0 ? (
              <div className={styles.empty}>
                <p className={styles.emptyTitle}>{t('alerts.empty')}</p>
                {/* Never blank: the current risk for each field instead (PRD §7.6), streamed because it may take a while. */}
                <Suspense fallback={<p className={styles.muted}>{t('state.loading')}</p>}><CurrentRisk t={t} now={now} /></Suspense>
              </div>
            ) : (
              <AlertsClient alerts={alerts.data.alerts} focusId={focus} unit={unit} renderedAt={now.toISOString()} />
            )}
          </div>
        </div>
    </PageMain>
  );
}

async function CurrentRisk({ t, now }: { t: Translator; now: Date }) {
  const [fields, decisions] = await Promise.all([getFields(), getDecisionsToday()]);
  if (!fields.ok || fields.data.length === 0) return null;
  const byField = new Map((decisions.ok ? decisions.data : []).map((d) => [d.field_id, d]));
  return (
    <>
      <h2 className={styles.h2}>{t('alerts.currentRisk')}</h2>
      <ul className={styles.riskRows}>
        {fields.data.map((f) => {
          const model = cardModel(byField.get(f.id), now);
          return (
            <li key={f.id} className={styles.riskRow}>
              <span>{f.name}</span>
              <RiskBadge level={model.level} kind={model.risk?.kind} size="sm" t={t} />
            </li>
          );
        })}
      </ul>
    </>
  );
}
