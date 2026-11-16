'use client';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import type { Alert } from '@fasalalert/shared/api';
import { CloudRain, IndianRupee, Snowflake, ThermometerSun, Truck } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { Button } from '@/components/UI/Button';
import { FilterChip } from '@/components/UI/Chips';
import { useToast } from '@/components/UI/Toast';
import { clientApi } from '@/lib/client-api';
import { daysBetween, formatDayDate, istDateKey } from '@/lib/format';
import { alertFilterOf, type AlertFilter } from '@/lib/risk';
import { AlertCard } from './AlertCard';
import styles from './AlertsClient.module.css';

const FILTERS: { key: AlertFilter; icon?: ReactNode }[] = [
  { key: 'all' },
  { key: 'frost', icon: <Snowflake size={20} aria-hidden="true" /> },
  { key: 'heat', icon: <ThermometerSun size={20} aria-hidden="true" /> },
  { key: 'rain', icon: <CloudRain size={20} aria-hidden="true" /> },
  { key: 'transport', icon: <Truck size={20} aria-hidden="true" /> },
  { key: 'price', icon: <IndianRupee size={20} aria-hidden="true" /> },
];

/** R6 list: filter chips (client-side), day groups, newest first (PRD §7.6, design.md 12.6). */
export function AlertsClient({ alerts, focusId, unit, renderedAt }: { alerts: Alert[]; focusId: number | null; unit: 'celsius' | 'fahrenheit'; renderedAt: string }) {
  const { t, locale } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [filter, setFilter] = useState<AlertFilter>('all');
  const [readAt, setReadAt] = useState<Record<number, string>>({});
  const items = useMemo(() => alerts.map((a) => (readAt[a.id] && !a.read_at ? { ...a, read_at: readAt[a.id]! } : a)), [alerts, readAt]);
  useEffect(() => {
    if (focusId) document.getElementById(`alert-${focusId}`)?.scrollIntoView({ block: 'center' });
  }, [focusId]);

  const now = useMemo(() => new Date(renderedAt), [renderedAt]);
  const shown = items
    .filter((a) => filter === 'all' || alertFilterOf(a.kind) === filter)
    .sort((a, b) => (b.sent_at ?? b.created_at).localeCompare(a.sent_at ?? a.created_at));
  const groups = new Map<string, Alert[]>();
  for (const a of shown) {
    const key = istDateKey(a.sent_at ?? a.created_at);
    groups.set(key, [...(groups.get(key) ?? []), a]);
  }
  const today = istDateKey(now);
  const groupLabel = (key: string) => {
    const diff = daysBetween(key, today);
    return diff === 0 ? t('alerts.group.today') : diff === 1 ? t('alerts.group.yesterday') : formatDayDate(key, locale, now);
  };

  const markRead = async (id: number): Promise<boolean> => {
    const r = await clientApi<Alert>(`alerts/${id}/read`, { method: 'POST' });
    if (!r.ok) return false;
    setReadAt((m) => ({ ...m, [id]: (r.data && r.data.read_at) || new Date().toISOString() }));
    toast(t('alerts.markedRead'));
    router.refresh(); // the tab and bell badges decrease (PRD §7.6)
    return true;
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.filters} role="group" aria-label={t('alerts.filterLabel')}>
        {FILTERS.map((f) => (
          <FilterChip key={f.key} pressed={filter === f.key} onClick={() => setFilter(f.key)} icon={f.icon}>{t(`alerts.filter.${f.key}`)}</FilterChip>
        ))}
      </div>
      {shown.length === 0 && filter !== 'all' ? (
        <div className={styles.empty}>
          <p>{t('alerts.filteredEmpty', { kind: filter })}</p>
          <Button variant="secondary" onClick={() => setFilter('all')}>{t('alerts.showAll')}</Button>
        </div>
      ) : null}
      {[...groups.entries()].map(([key, list]) => (
        <section key={key} aria-labelledby={`g-${key}`} className={styles.group}>
          <h2 id={`g-${key}`} className={styles.groupTitle}>{groupLabel(key)}</h2>
          <ul className={styles.list}>
            {list.map((a) => <li key={a.id}><AlertCard alert={a} onMarkRead={markRead} defaultOpen={a.id === focusId} unit={unit} /></li>)}
          </ul>
        </section>
      ))}
    </div>
  );
}
