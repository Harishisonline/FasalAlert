'use client';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { useI18n } from '@/components/I18n';
import { Banner } from '@/components/UI/Banner';
import { useToast } from '@/components/UI/Toast';
import { formatDateTime } from '@/lib/format';

/**
 * Offline cue on every AppShell page (design.md 20.5): an info banner with the time the data on
 * screen was saved, and data-offline on <html> so "Last known" labels appear. Back online is a toast.
 */
export function OfflineBanner() {
  const { t, locale } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [offline, setOffline] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  useEffect(() => {
    const update = (isOffline: boolean, announce: boolean) => {
      setOffline(isOffline);
      const el = document.querySelector<HTMLElement>('[data-rendered-at]');
      setSavedAt(el?.dataset.renderedAt ?? null);
      if (isOffline) document.documentElement.dataset.offline = '';
      else delete document.documentElement.dataset.offline;
      if (!isOffline && announce) {
        toast(t('state.backOnline'));
        router.refresh();
      }
    };
    update(!navigator.onLine, false);
    const on = () => update(false, true);
    const off = () => update(true, false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    return () => { window.removeEventListener('online', on); window.removeEventListener('offline', off); };
  }, [router, t, toast]);
  if (!offline) return null;
  return (
    <Banner variant="info" icon="wifi-off">
      {savedAt ? t('state.offline.banner', { time: formatDateTime(savedAt, locale) }) : t('state.offline.bannerNoTime')}
    </Banner>
  );
}
