'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useId, useState } from 'react';
import { useOnline } from '@/lib/hooks';
import type { UserMeResponse } from '@fasalalert/shared/api';
import { ChevronRight, LogOut, Phone, SlidersHorizontal } from '@/components/Icon';
import { DeliverySettings } from '@/components/Alert/DeliverySettings';
import { useI18n } from '@/components/I18n';
import { LanguageRadioCards, swapLocale } from '@/components/Nav/LanguageSwitcher';
import { SocialLinks } from '@/components/Nav/SocialLinks';
import { Button } from '@/components/UI/Button';
import { Segmented } from '@/components/UI/Chips';
import { Disclosure } from '@/components/UI/Disclosure';
import { signOut } from '@/lib/auth-client';
import { clientApi } from '@/lib/client-api';
import { KISAN_CALL_CENTRE } from '@/lib/config';
import { telHref } from '@/lib/format';
import type { Locale, Theme } from '@/lib/locales';
import styles from './SettingsForm.module.css';

/**
 * R9a Settings as a single form where every control saves itself (PRD §7.9, design.md 12.9, D-10).
 * Optimistic, then revert with an inline error: the UI never disagrees with the server.
 */
export function SettingsForm({ me, theme: initialTheme }: { me: UserMeResponse; theme: Theme }) {
  const { t, locale } = useI18n();
  const router = useRouter();
  const id = useId();
  const [name, setName] = useState(me.name ?? '');
  const [savedName, setSavedName] = useState(me.name ?? '');
  const [lang, setLang] = useState<Locale>(locale);
  const [temp, setTemp] = useState(me.temp_unit);
  const [area, setArea] = useState(me.area_unit);
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<string | null>(null);
  const online = useOnline();

  const flash = (key: string) => { setSaved(key); setTimeout(() => setSaved((k) => (k === key ? null : k)), 2000); };
  const patchMe = async (key: string, body: Record<string, unknown>): Promise<boolean> => {
    setErrors((e) => ({ ...e, [key]: '' }));
    const r = await clientApi('users/me', { method: 'PATCH', body });
    if (!r.ok) { setErrors((e) => ({ ...e, [key]: r.kind === 'network' ? t('common.noConnection') : t('common.saveFailed') })); return false; }
    flash(key);
    return true;
  };

  const saveName = async () => {
    const v = name.trim().slice(0, 60);
    if (v === savedName) return;
    if (await patchMe('name', { name: v })) { setSavedName(v); router.refresh(); } else setName(savedName);
  };

  const changeLang = async (l: Locale) => {
    const prev = lang;
    setLang(l);
    const ok = await patchMe('lang', { preferred_locale: l });
    if (!ok) { setLang(prev); setErrors((e) => ({ ...e, lang: t('settings.langFailed') })); return; }
    // The session token is re-issued so its claims carry the new language (PRD §7.9).
    await fetch('/api/auth/refresh', { method: 'POST', credentials: 'same-origin' }).catch(() => null);
    document.cookie = `NEXT_LOCALE=${l}; path=/; max-age=31536000; samesite=lax`;
    const y = window.scrollY;
    sessionStorage.setItem('fa:scroll', String(y));
    window.location.assign(swapLocale(window.location.pathname, l));
  };
  useEffect(() => {
    const y = sessionStorage.getItem('fa:scroll');
    if (y) { sessionStorage.removeItem('fa:scroll'); window.scrollTo(0, Number(y)); }
  }, []);

  const changeUnit = async (key: 'temp' | 'area', value: string) => {
    if (key === 'temp') {
      const prev = temp;
      setTemp(value as typeof temp);
      if (!(await patchMe('temp', { temp_unit: value }))) setTemp(prev); else router.refresh();
    } else {
      const prev = area;
      setArea(value as typeof area);
      if (!(await patchMe('area', { area_unit: value }))) setArea(prev); else router.refresh();
    }
  };

  const changeTheme = (v: Theme) => {
    setTheme(v);
    document.cookie = `theme=${v}; path=/; max-age=31536000; samesite=lax`;
    document.documentElement.dataset.theme = v;
    flash('theme');
  };

  const status = (key: string) => (
    <span className={styles.status} aria-live="polite">
      {errors[key] ? <span className={styles.error}>{errors[key]}</span> : saved === key ? <span className={styles.saved}>{t('common.saved')}</span> : null}
    </span>
  );

  return (
    <div className={styles.form}>
      {!online ? <p className={styles.offline} role="status">{t('common.offlineSettings')}</p> : null}
      <section className={styles.group} aria-labelledby={`${id}-profile`}>
        <h2 id={`${id}-profile`} className={styles.h2}>{t('settings.profile')}</h2>
        <div className={styles.row}>
          <label htmlFor={`${id}-name`} className={styles.label}>{t('settings.name')}</label>
          <div className={styles.control}>
            <input id={`${id}-name`} className={styles.input} value={name} maxLength={60} disabled={!online} autoComplete="name"
              onChange={(e) => setName(e.target.value)} onBlur={() => void saveName()} onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
            {status('name')}
          </div>
        </div>
        <div className={styles.row}>
          <span className={styles.label}>{t('settings.phone')}</span>
          <p className={styles.control}><span className="tabular">{me.phone_masked}</span> <span className={styles.muted}>{t('settings.phoneNote')}</span></p>
        </div>
      </section>

      <section className={styles.group} aria-labelledby={`${id}-lang`}>
        <h2 id={`${id}-lang`} className={styles.h2}>{t('settings.language')}</h2>
        <LanguageRadioCards value={lang} onChange={(l) => void changeLang(l)} legend={t('settings.language')} disabled={!online} name={`${id}-language`} />
        {status('lang')}
      </section>

      <section className={styles.group} aria-labelledby={`${id}-units`}>
        <h2 id={`${id}-units`} className={styles.h2}>{t('settings.units')}</h2>
        <div className={styles.row}>
          <span className={styles.label}>{t('settings.temperature')}</span>
          <div className={styles.control}>
            <Segmented label={t('settings.temperature')} value={temp} disabled={!online} onChange={(v) => void changeUnit('temp', v)}
              options={[{ value: 'celsius', label: t('settings.celsius') }, { value: 'fahrenheit', label: t('settings.fahrenheit') }]} />
            {status('temp')}
          </div>
        </div>
        <div className={styles.row}>
          <span className={styles.label}>{t('settings.area')}</span>
          <div className={styles.control}>
            <Segmented label={t('settings.area')} value={area} disabled={!online} onChange={(v) => void changeUnit('area', v)}
              options={[{ value: 'hectare', label: t('settings.hectare') }, { value: 'acre', label: t('settings.acre') }]} />
            {status('area')}
          </div>
        </div>
      </section>

      <section className={styles.group} aria-labelledby={`${id}-alerts`}>
        <h2 id={`${id}-alerts`} className={styles.h2}>{t('settings.alerts')}</h2>
        <DeliverySettings initial={me.preferences} />
      </section>

      <Link href={`/${locale}/settings/calibration`} className={styles.linkRow}>
        <SlidersHorizontal size={24} aria-hidden="true" />
        <span>{t('settings.calibrationLink')}</span>
        <ChevronRight size={20} aria-hidden="true" />
      </Link>

      <section className={styles.group} aria-labelledby={`${id}-appearance`}>
        <h2 id={`${id}-appearance`} className={styles.h2}>{t('settings.appearance')}</h2>
        <Segmented label={t('settings.appearance')} value={theme} onChange={(v) => changeTheme(v as Theme)}
          options={[{ value: 'light', label: t('settings.light') }, { value: 'dark', label: t('settings.dark') }]} />
        {status('theme')}
      </section>

      <section className={styles.group} aria-labelledby={`${id}-account`}>
        <h2 id={`${id}-account`} className={styles.h2}>{t('settings.account')}</h2>
        <p className={styles.muted}>{t('settings.signedInAs', { phone: me.phone_masked })}</p>
        <div className={styles.actions}>
          <Button variant="danger" icon={<LogOut size={20} aria-hidden="true" />} onClick={() => void signOut(locale)}>{t('nav.signOut')}</Button>
        </div>
        {/* Account deletion has no API yet, so there is no button for it (docs/UX_QA_AUDIT.md SET-01). */}
        <p className={styles.muted}>{t('settings.deleteNote')}</p>
      </section>

      <section className={styles.group} aria-labelledby={`${id}-help`} id="help">
        <h2 id={`${id}-help`} className={styles.h2}>{t('settings.help')}</h2>
        <ul className={styles.helpList}>
          <li><strong>{t('settings.help.decisionTitle')}</strong> {t('settings.help.decision')}</li>
          <li><strong>{t('settings.help.levelsTitle')}</strong> {t('settings.help.levels')}</li>
          <li><strong>{t('settings.help.unavailableTitle')}</strong> {t('settings.help.unavailable')}</li>
        </ul>
        <div className={styles.actions}>
          {me.district_kvk ? <a className={styles.call} href={telHref(me.district_kvk.phone)}><Phone size={20} aria-hidden="true" /> {t('abstain.callKvk', { name: me.district_kvk.name })}</a> : null}
          <a className={styles.call} href={telHref(KISAN_CALL_CENTRE)}><Phone size={20} aria-hidden="true" /> {t('settings.help.kcc', { phone: KISAN_CALL_CENTRE })}</a>
        </div>
        <Link href={`/?lang=${locale}#trust`} className={styles.linkRow}><span>{t('settings.help.limits')}</span><ChevronRight size={20} aria-hidden="true" /></Link>
      </section>

      <section className={styles.group} aria-labelledby={`${id}-about`}>
        <h2 id={`${id}-about`} className={styles.h2}>{t('settings.about')}</h2>
        <p>{t('settings.credits')}</p>
        <SocialLinks t={t} />
        <Disclosure label={t('settings.creditsTitle')}>
          <p className={styles.muted}>{t('settings.dataCredits')}</p>
          <p className={styles.muted}>{t('settings.creditsLicences')}</p>
        </Disclosure>
        <Disclosure label={t('settings.install')}>
          <p className={styles.muted}>{t('settings.installHelp')}</p>
        </Disclosure>
      </section>
    </div>
  );
}
