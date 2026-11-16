'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocalStorage } from '@/lib/hooks';
import { Check, Phone, WifiOff, X } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { DecisionCard } from '@/components/Risk/DecisionCard';
import { Button, ButtonLink } from '@/components/UI/Button';
import { useToast } from '@/components/UI/Toast';
import { formatDateTime, spellDigits, telHref } from '@/lib/format';
import type { LastKnownSnapshot } from '@/lib/offline';
import type { ViewCtx } from '@/lib/view';
import styles from './System.module.css';

const KCC = '1800-180-1551';

/** R10 Offline (PRD §7.11, design.md 12.11): last known decisions, what works, phone numbers, Try again. */
export function OfflineView() {
  const { t, locale } = useI18n();
  const toast = useToast();
  const heading = useRef<HTMLHeadingElement>(null);
  const raw = useLocalStorage('fa:last-known');
  const snap = useMemo<LastKnownSnapshot | null>(() => { try { return raw ? JSON.parse(raw) as LastKnownSnapshot : null; } catch { return null; } }, [raw]);
  const [back, setBack] = useState(false);
  const goBack = () => {
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- the original URL needs a full network load
    if (window.location.pathname.endsWith('/offline')) window.location.assign(`/${locale}/home`);
    else window.location.reload();
  };
  useEffect(() => {
    heading.current?.focus();
    const onOnline = () => {
      setBack(true);
      toast(t('state.backOnline'));
      setTimeout(() => goBack(), 1000);
    };
    window.addEventListener('online', onOnline);
    return () => window.removeEventListener('online', onOnline);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const now = useMemo(() => new Date(), []);
  const ctx: ViewCtx = { t, locale, now, unit: 'celsius' };
  const fields = new Map((snap?.fields ?? []).map((f) => [f.id, f]));
  return (
    <div className={styles.system}>
      <WifiOff size={48} aria-hidden="true" className={styles.icon} />
      <h1 ref={heading} tabIndex={-1} className={styles.title}>{t('offline.title')}</h1>
      <p className={styles.body}>{t('offline.body')}</p>
      <section className={styles.section} aria-labelledby="lk-h">
        {snap && snap.decisions.length ? (
          <>
            <h2 id="lk-h" className={styles.h2}>{t('offline.lastKnown', { time: formatDateTime(snap.savedAt, locale, now) })}</h2>
            <ul className={styles.cards}>
              {snap.decisions.map((d) => {
                const f = fields.get(d.field_id);
                if (!f) return null;
                return (
                  <li key={d.field_id}>
                    <DecisionCard variant="offline" field={{ id: f.id, name: f.name, crop: f.crop, variety: f.variety }} decision={d} ctx={ctx}
                      href={`/${locale}/field/${f.id}`} renderedAt={snap.savedAt} />
                  </li>
                );
              })}
            </ul>
          </>
        ) : <p id="lk-h" className={styles.body}>{t('offline.nothingSaved')}</p>}
      </section>
      <section className={styles.section} aria-labelledby="works-h">
        <h2 id="works-h" className={styles.h2}>{t('offline.works')}</h2>
        <ul className={styles.list}>
          <li className={styles.listItem}><Check size={20} aria-hidden="true" className={styles.ok} />{t('offline.works1')}</li>
          <li className={styles.listItem}><Check size={20} aria-hidden="true" className={styles.ok} />{t('offline.works2')}</li>
        </ul>
        <h2 className={styles.h2}>{t('offline.needs')}</h2>
        <ul className={styles.list}>
          <li className={styles.listItem}><X size={20} aria-hidden="true" className={styles.no} />{t('offline.needs1')}</li>
        </ul>
      </section>
      <section className={styles.section} aria-labelledby="advice-h">
        <h2 id="advice-h" className={styles.h2}>{t('offline.needAdvice')}</h2>
        {snap?.kvk ? (
          <div className={styles.contact}>
            <span>{snap.kvk.name} <span className="tabular" lang="en">{snap.kvk.phone}</span></span>
            <ButtonLink href={telHref(snap.kvk.phone)} variant="call" icon={<Phone size={20} aria-hidden="true" />} aria-label={t('common.callNamed', { name: snap.kvk.name, digits: spellDigits(snap.kvk.phone) })}>{t('common.call')}</ButtonLink>
          </div>
        ) : null}
        <div className={styles.contact}>
          <span>{t('offline.kcc')}</span>
          <ButtonLink href={telHref(KCC)} variant="call" icon={<Phone size={20} aria-hidden="true" />} aria-label={t('common.callNamed', { name: t('abstain.kcc'), digits: spellDigits(KCC) })}>{t('common.call')}</ButtonLink>
        </div>
      </section>
      <div className={styles.actions}>
        <Button size="lg" fullWidth onClick={goBack}>{t('common.tryAgain')}</Button>
        {back ? <Button variant="secondary" onClick={goBack}>{t('offline.goNow')}</Button> : null}
      </div>
    </div>
  );
}
