'use client';
import { useEffect, useId, useRef, useState } from 'react';
import { useClientValue, useOnline } from '@/lib/hooks';
import type { Preferences } from '@fasalalert/shared/api';
import { useI18n } from '@/components/I18n';
import { Button } from '@/components/UI/Button';
import { Dialog } from '@/components/UI/Dialog';
import { Switch } from '@/components/UI/Switch';
import { clientApi } from '@/lib/client-api';
import { pushSupport, subscribePush, unsubscribePush, type PushSupport } from '@/lib/push';
import styles from './DeliverySettings.module.css';

type Channel = 'sms' | 'whatsapp' | 'push';

export function quietRange(t: (k: string, v?: Record<string, string>) => string, start: string | null, end: string | null): string | null {
  if (!start || !end) return null;
  return start > end ? t('delivery.overnight', { start, end }) : t('delivery.range', { start, end });
}

/**
 * Channel switches and quiet hours (PRD §7.6, §7.9, design.md 12.6). Optimistic, reverted on failure,
 * never left in a state the server disagrees with. Disabled offline (design.md 20.5).
 */
export function DeliverySettings({ initial, onChange }: { initial: Preferences; onChange?: (p: Preferences) => void }) {
  const { t } = useI18n();
  const id = useId();
  const [prefs, setPrefs] = useState(initial);
  const [error, setError] = useState<{ key: string; message: string } | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const online = useOnline();
  const detected = useClientValue<PushSupport>(pushSupport, 'unsupported');
  const [pushOverride, setPush] = useState<PushSupport | null>(null);
  const push = pushOverride ?? detected;
  const [explain, setExplain] = useState(false);
  const [confirmOff, setConfirmOff] = useState<Channel | null>(null);
  const [savedKey, setSavedKey] = useState<string | null>(null);
  const committed = useRef(initial);

  useEffect(() => { onChange?.(prefs); }, [prefs, onChange]);

  const patch = async (key: string, body: Record<string, unknown>, next: Preferences): Promise<boolean> => {
    setPrefs(next);
    setSaving(key);
    setError(null);
    const r = await clientApi<Preferences>('users/me/preferences', { method: 'PATCH', body });
    setSaving(null);
    if (!r.ok) {
      setPrefs(committed.current);
      setError({ key, message: t('common.saveFailed') });
      return false;
    }
    const saved = r.data && typeof r.data === 'object' && 'channels' in r.data ? { ...next, ...r.data, channel_availability: r.data.channel_availability ?? next.channel_availability } : next;
    committed.current = saved;
    setPrefs(saved);
    setSavedKey(key);
    setTimeout(() => setSavedKey((k) => (k === key ? null : k)), 2000);
    return true;
  };

  const setChannel = async (ch: Channel, value: boolean, extra: Record<string, unknown> = {}) => {
    const next = { ...prefs, channels: { ...prefs.channels, [ch]: value } };
    return patch(ch, { channels: { [ch]: value }, ...extra }, next);
  };

  const toggle = async (ch: Channel, value: boolean) => {
    if (!value) {
      const others = (['sms', 'whatsapp', 'push'] as Channel[]).filter((c) => c !== ch && prefs.channels[c]);
      if (others.length === 0) { setConfirmOff(ch); return; }
      if (ch === 'push') { await unsubscribePush(); await setChannel('push', false, { push_subscription: null }); return; }
      await setChannel(ch, false);
      return;
    }
    if (ch === 'push') { setExplain(true); return; }
    await setChannel(ch, true);
  };

  const allowPush = async () => {
    setExplain(false);
    const sub = await subscribePush();
    if (!sub.ok) {
      setPush(pushSupport());
      setError({ key: 'push', message: sub.reason === 'denied' ? t('delivery.pushBlocked') : t('delivery.pushFailed') });
      return;
    }
    const ok = await setChannel('push', true, { push_subscription: sub.subscription });
    if (!ok) await unsubscribePush();
  };

  const avail = prefs.channel_availability;
  const quietOn = Boolean(prefs.quiet_hours_start && prefs.quiet_hours_end);
  const disabledAll = !online;
  const pushNote = !avail.push ? t('delivery.pushUnavailable')
    : push === 'no-key' ? t('delivery.pushNoKey')
      : push === 'blocked' ? t('delivery.pushBlocked')
        : push === 'ios-needs-install' ? t('delivery.pushIos')
          : push === 'unsupported' ? t('delivery.pushUnsupported') : undefined;
  const pushDisabled = disabledAll || !avail.push || (push !== 'ok' && !prefs.channels.push);
  const label = (key: string, text: string) => (savedKey === key ? `${text} · ${t('common.saved')}` : text);

  return (
    <div className={styles.settings}>
      {disabledAll ? <p className={styles.offline} role="status">{t('common.offlineSettings')}</p> : null}
      <Switch label={label('sms', t('delivery.sms'))} description={t('delivery.smsDesc')} checked={prefs.channels.sms} onChange={(v) => void toggle('sms', v)}
        disabled={disabledAll || saving === 'sms' || !avail.sms} onText={t('common.on')} offText={t('common.off')} error={error?.key === 'sms' ? error.message : undefined}
        note={prefs.sms_dev_outbox ? t('delivery.smsDevOutbox') : !avail.sms ? t('delivery.smsUnavailable') : undefined} />
      <Switch label={label('whatsapp', t('delivery.whatsapp'))} description={t('delivery.whatsappDesc')} checked={avail.whatsapp && prefs.channels.whatsapp} onChange={(v) => void toggle('whatsapp', v)}
        disabled={disabledAll || !avail.whatsapp || saving === 'whatsapp'} onText={t('common.on')} offText={t('common.off')}
        note={!avail.whatsapp ? t('delivery.whatsappUnavailable') : undefined} error={error?.key === 'whatsapp' ? error.message : undefined} />
      <Switch label={label('push', t('delivery.push'))} description={t('delivery.pushDesc')} checked={prefs.channels.push} onChange={(v) => void toggle('push', v)}
        disabled={pushDisabled || saving === 'push'} onText={t('common.on')} offText={t('common.off')} note={pushNote} error={error?.key === 'push' ? error.message : undefined} />
      <Switch label={label('quiet', t('delivery.quiet'))} description={t('delivery.quietDesc')} checked={quietOn} disabled={disabledAll || saving === 'quiet'} onText={t('common.on')} offText={t('common.off')}
        onChange={(v) => {
          const next = v ? { ...prefs, quiet_hours_start: prefs.quiet_hours_start ?? '22:00', quiet_hours_end: prefs.quiet_hours_end ?? '06:00' } : { ...prefs, quiet_hours_start: null, quiet_hours_end: null };
          void patch('quiet', { quiet_hours_start: next.quiet_hours_start, quiet_hours_end: next.quiet_hours_end }, next);
        }}
        note={quietOn ? quietRange(t as never, prefs.quiet_hours_start, prefs.quiet_hours_end) : undefined}
        error={error?.key === 'quiet' ? error.message : undefined} />
      {quietOn ? (
        <div className={styles.times}>
          {(['quiet_hours_start', 'quiet_hours_end'] as const).map((k) => (
            <div key={k} className={styles.time}>
              <label htmlFor={`${id}-${k}`} className={styles.timeLabel}>{k === 'quiet_hours_start' ? t('delivery.start') : t('delivery.end')}</label>
              <input id={`${id}-${k}`} type="time" className={styles.timeInput} value={prefs[k] ?? ''} disabled={disabledAll}
                onChange={(e) => setPrefs({ ...prefs, [k]: e.target.value })}
                onBlur={(e) => {
                  const next = { ...prefs, [k]: e.target.value };
                  if (e.target.value && e.target.value !== committed.current[k]) void patch('quiet', { [k]: e.target.value }, next);
                }} />
            </div>
          ))}
        </div>
      ) : null}
      <p className="visually-hidden" aria-live="polite">{savedKey ? t('common.saved') : ''}</p>
      <Dialog open={explain} title={t('delivery.pushExplainTitle')} onCancel={() => setExplain(false)}
        actions={<><Button variant="secondary" onClick={() => setExplain(false)}>{t('delivery.notNow')}</Button><Button onClick={() => void allowPush()}>{t('delivery.allow')}</Button></>}>
        <p>{t('delivery.pushExplain')}</p>
        {push === 'ios-needs-install' ? <p>{t('delivery.pushIos')}</p> : null}
      </Dialog>
      <Dialog open={confirmOff !== null} title={t('delivery.lastChannelTitle')} onCancel={() => setConfirmOff(null)}
        actions={<>
          <Button variant="secondary" onClick={() => setConfirmOff(null)}>{t('delivery.keepOn')}</Button>
          <Button onClick={() => { const ch = confirmOff!; setConfirmOff(null); if (ch === 'push') { void unsubscribePush(); void setChannel('push', false, { push_subscription: null }); } else void setChannel(ch, false); }}>{t('delivery.turnOff')}</Button>
        </>}>
        <p>{t('delivery.lastChannel', { channel: confirmOff ? t(`delivery.${confirmOff}`) : '' })}</p>
      </Dialog>
    </div>
  );
}
