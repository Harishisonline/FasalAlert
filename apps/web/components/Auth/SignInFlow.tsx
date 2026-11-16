'use client';
import { useEffect, useId, useRef, useState, type ClipboardEvent, type FormEvent } from 'react';
import type { OtpRequestResponse, User } from '@fasalalert/shared/api';
import { ArrowLeft, Check, Copy, Phone } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { LanguageRadioCards, LanguageSwitcher } from '@/components/Nav/LanguageSwitcher';
import { ThemeToggle } from '@/components/Nav/ThemeToggle';
import { Wordmark } from '@/components/Nav/Wordmark';
import { Banner } from '@/components/UI/Banner';
import { Button, ButtonLink } from '@/components/UI/Button';
import { FieldMessage } from '@/components/UI/Field';
import { parseErrorBody } from '@/lib/api-types';
import { clientApi } from '@/lib/client-api';
import { formatClock, groupPhone } from '@/lib/format';
import { isLocale, type Locale } from '@/lib/locales';
import { postSignInTarget } from '@/lib/auth-flow';
import { isValidPhone, normalisePhone } from '@/lib/phone';
import { nowMs } from '@/lib/hooks';
import styles from './SignInFlow.module.css';

const HELPLINE = 'tel:18001801551';
const MAX_ATTEMPTS = 5;

type Step = 'phone' | 'code' | 'language';

async function post(path: string, body: unknown) {
  try {
    const res = await fetch(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), credentials: 'same-origin' });
    const json = await res.json().catch(() => null);
    return { status: res.status, ok: res.ok, json, error: res.ok ? null : parseErrorBody(json) };
  } catch {
    return { status: 0, ok: false, json: null, error: null };
  }
}

/** R2 sign in: phone, 6-digit SMS code, then language for new accounts (PRD §7.2, design.md 12.2). */
export function SignInFlow({ next, expired: sessionExpired }: { next: string | null; expired: boolean }) {
  const { t, locale } = useI18n();
  const id = useId();
  const [step, setStep] = useState<Step>('phone');
  const [digits, setDigits] = useState('');
  const [touched, setTouched] = useState(false);
  const [phoneError, setPhoneError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sendLockedUntil, setSendLockedUntil] = useState<number | null>(null);
  const [code, setCode] = useState('');
  const [codeFocused, setCodeFocused] = useState(false);
  const [codeError, setCodeError] = useState<string | null>(null);
  const [attemptsLeft, setAttemptsLeft] = useState(MAX_ATTEMPTS);
  const [locked, setLocked] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [shake, setShake] = useState(0);
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [resendAt, setResendAt] = useState<number | null>(null);
  const [sentAt, setSentAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => nowMs());
  const [announce, setAnnounce] = useState('');
  const [lang, setLang] = useState<Locale>(locale);
  const [langSaving, setLangSaving] = useState(false);
  const [langError, setLangError] = useState<string | null>(null);
  const [pending, setPending] = useState<{ hasFields: boolean } | null>(null);
  const [devOutbox, setDevOutbox] = useState(false);
  const [demoCode, setDemoCode] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const codeRef = useRef<HTMLInputElement>(null);
  const phoneRef = useRef<HTMLInputElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const webotp = useRef<AbortController | null>(null);
  const resendAnnounced = useRef(false);

  useEffect(() => {
    const iv = setInterval(() => setNow(nowMs()), 1000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => { headingRef.current?.focus(); }, [step]);

  const expired = step === 'code' && expiresAt !== null && now >= expiresAt;
  const resendIn = resendAt ? Math.max(0, Math.ceil((resendAt - now) / 1000)) : 0;
  const sendLockIn = sendLockedUntil ? Math.max(0, Math.ceil((sendLockedUntil - now) / 1000)) : 0;
  const showNoCodeNotice = sentAt !== null && now - sentAt > 120_000;

  useEffect(() => {
    if (step === 'code' && resendAt && resendIn === 0 && !resendAnnounced.current) {
      resendAnnounced.current = true;
      setAnnounce(t('signin.resendReady'));
    }
  }, [resendIn, resendAt, step, t]);

  const phoneValid = isValidPhone(digits);
  const showPhoneError = touched && digits.length > 0 && !phoneValid;

  const startWebOtp = () => {
    if (typeof window === 'undefined' || !('OTPCredential' in window)) return;
    webotp.current?.abort();
    const ac = new AbortController();
    webotp.current = ac;
    navigator.credentials
      .get({ otp: { transport: ['sms'] }, signal: ac.signal } as CredentialRequestOptions)
      .then((cred) => {
        const otp = (cred as unknown as { code?: string } | null)?.code;
        if (otp && /^\d{6}$/.test(otp)) { setCode(otp); void verify(otp); }
      })
      .catch(() => { /* cancelled or unsupported */ });
  };

  const requestCode = async () => {
    if (sending) return;
    if (!phoneValid) { setTouched(true); return; }
    setSending(true);
    setPhoneError(null);
    const r = await post('/api/auth/otp/request', { phone: `+91${digits}` });
    setSending(false);
    if (r.ok) {
      const body = r.json as OtpRequestResponse;
      const n = nowMs();
      setExpiresAt(n + (body.expires_in || 300) * 1000);
      setResendAt(n + Math.max(60, body.retry_after || 0) * 1000);
      setSentAt(n);
      setDevOutbox(body.delivery === 'dev_outbox');
      setDemoCode(typeof body.demo_code === 'string' && /^\d{6}$/.test(body.demo_code) ? body.demo_code : null);
      setCopied(false);
      resendAnnounced.current = false;
      setCode('');
      setCodeError(null);
      setAttemptsLeft(MAX_ATTEMPTS);
      setLocked(false);
      setStep('code');
      startWebOtp();
      setTimeout(() => codeRef.current?.focus(), 50);
      return;
    }
    if (r.status === 429 || r.error?.code === 'rate_limited') {
      const after = Number(r.error?.details?.retry_after) || 3600;
      setSendLockedUntil(nowMs() + after * 1000);
      setResendAt(nowMs() + after * 1000);
      setPhoneError(t('signin.rateLimited', { minutes: Math.max(1, Math.ceil(after / 60)) }));
      return;
    }
    if (r.status === 400 && r.error?.details?.field === 'phone') { setPhoneError(t('signin.invalidPhone')); return; }
    setPhoneError(r.status === 0 ? t('common.noConnection') : t('common.serverError'));
  };

  const verify = async (value: string) => {
    if (locked || expired || value.length !== 6 || verifying) return;
    webotp.current?.abort();
    setVerifying(true);
    setCodeError(null);
    const r = await post('/api/auth/otp/verify', { phone: `+91${digits}`, code: value });
    setVerifying(false);
    if (r.ok) {
      const body = r.json as { user: User; is_new_user: boolean; has_fields: boolean };
      if (body.is_new_user) {
        setPending({ hasFields: body.has_fields });
        setLang(body.user?.preferred_locale ?? locale);
        setStep('language');
        return;
      }
      const userLocale = isLocale(body.user?.preferred_locale) ? body.user.preferred_locale : locale;
      window.location.assign(postSignInTarget({ hasFields: body.has_fields, next, locale: userLocale }));
      return;
    }
    const reason = String(r.error?.details?.reason ?? '');
    if (reason === 'expired') { setExpiresAt(nowMs() - 1); return; }
    if (r.status === 0) { setCodeError(t('common.noConnection')); return; }
    if (r.status === 429 || reason === 'locked' || reason === 'too_many_attempts') { setLocked(true); setAttemptsLeft(0); return; }
    if (r.status >= 500) { setCodeError(t('common.serverError')); return; }
    const serverLeft = Number(r.error?.details?.attempts_left ?? r.error?.details?.attempts_remaining);
    const left = Number.isFinite(serverLeft) ? serverLeft : attemptsLeft - 1;
    setAttemptsLeft(left);
    setShake((s) => s + 1);
    setCode('');
    if (left <= 0) { setLocked(true); return; }
    setCodeError(t('signin.wrongCode', { count: left }));
    codeRef.current?.focus();
  };

  const onCodeChange = (raw: string) => {
    webotp.current?.abort();
    const v = raw.replace(/\D/g, '').slice(0, 6);
    setCode(v);
    if (v.length === 6) void verify(v);
  };

  const onPhonePaste = (e: ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    setDigits(normalisePhone(e.clipboardData.getData('text')));
    setTouched(true);
  };

  const continueLanguage = async () => {
    setLangSaving(true);
    setLangError(null);
    const r = await clientApi('users/me', { method: 'PATCH', body: { preferred_locale: lang } });
    setLangSaving(false);
    if (!r.ok) { setLangError(r.kind === 'network' ? t('common.noConnection') : t('common.saveFailed')); return; }
    document.cookie = `NEXT_LOCALE=${lang}; path=/; max-age=31536000; samesite=lax`;
    // A full load switches <html lang> and the session layout.
    window.location.assign(postSignInTarget({ hasFields: Boolean(pending?.hasFields), next, locale: lang }));
  };

  const onSubmitPhone = (e: FormEvent) => { e.preventDefault(); void requestCode(); };
  const onSubmitCode = (e: FormEvent) => { e.preventDefault(); void verify(code); };

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        {step === 'code' ? (
          <button type="button" className={styles.back} onClick={() => { webotp.current?.abort(); setStep('phone'); }} aria-label={t('nav.back')}>
            <ArrowLeft size={24} aria-hidden="true" />
          </button>
        ) : (
          <a href={`/?lang=${locale}`} className={styles.brandLink} aria-label={t('signin.backToLanding')}>
            <Wordmark showDevanagari={locale !== 'en'} devanagari={t('brand.devanagari')} />
          </a>
        )}
        <div className={styles.headerRight}>
          <ThemeToggle />
          <LanguageSwitcher />
        </div>
      </header>
      <main id="main" className={styles.main}>
        <div className={styles.card}>
          {sessionExpired && step === 'phone' ? <Banner variant="info">{t('signin.expiredSession')}</Banner> : null}

          {step === 'phone' ? (
            <form onSubmit={onSubmitPhone} className={styles.form} noValidate>
              <h1 ref={headingRef} tabIndex={-1} className={styles.h1}>{t('signin.title')}</h1>
              <p className={styles.help}>{t('signin.help')}</p>
              <p className={styles.newUser}>{t('signin.newUser')}</p>
              <div className={styles.field}>
                <label htmlFor={`${id}-phone`} className={styles.label}>{t('signin.phoneLabel')}</label>
                <div className={styles.phone} data-invalid={showPhoneError || phoneError ? true : undefined}>
                  <span className={styles.prefix} aria-hidden="true">{t('signin.prefix')}</span>
                  <input
                    ref={phoneRef}
                    id={`${id}-phone`}
                    type="tel"
                    inputMode="numeric"
                    autoComplete="tel-national"
                    value={groupPhone(digits)}
                    onChange={(e) => setDigits(normalisePhone(e.target.value))}
                    onBlur={() => setTouched(true)}
                    onPaste={onPhonePaste}
                    readOnly={sending}
                    aria-invalid={showPhoneError || phoneError ? true : undefined}
                    aria-describedby={showPhoneError || phoneError ? `${id}-phone-error` : undefined}
                    className={styles.phoneInput}
                  />
                </div>
                <FieldMessage id={`${id}-phone`} error={showPhoneError ? t('signin.invalidPhone') : phoneError ?? undefined} />
              </div>
              <Button type="submit" size="lg" fullWidth disabled={!phoneValid || sendLockIn > 0} loading={sending} loadingLabel={t('signin.sending')}>
                {sendLockIn > 0 ? t('signin.resendIn', { time: formatClock(sendLockIn) }) : t('signin.send')}
              </Button>
            </form>
          ) : null}

          {step === 'code' ? (
            <form onSubmit={onSubmitCode} className={styles.form} noValidate>
              <h1 ref={headingRef} tabIndex={-1} className={styles.h1}>{t('signin.codeTitle')}</h1>
              <p className={styles.help}>{t('signin.sentTo', { phone: `+91 ${groupPhone(digits)}` })}</p>
              {demoCode ? (
                <div className={styles.demo} role="status" aria-live="polite">
                  <p className={styles.demoTitle}>{t('signin.demoTitle')}</p>
                  <p className={styles.demoLead}>{t('signin.demoLead')}</p>
                  <div className={styles.demoRow}>
                    <code className={styles.demoCode}>{demoCode}</code>
                    <button
                      type="button"
                      className={styles.demoCopy}
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(demoCode);
                          setCopied(true);
                          setTimeout(() => setCopied(false), 2000);
                        } catch { /* clipboard may be denied */ }
                      }}
                    >
                      {copied ? <Check size={18} aria-hidden="true" /> : <Copy size={18} aria-hidden="true" />}
                      <span>{copied ? t('signin.demoCopied') : t('signin.demoCopy')}</span>
                    </button>
                  </div>
                </div>
              ) : devOutbox ? <Banner variant="info">{t('signin.devOutbox')}</Banner> : null}
              <Button variant="text" onClick={() => { webotp.current?.abort(); setStep('phone'); setTimeout(() => phoneRef.current?.focus(), 50); }}>{t('signin.changeNumber')}</Button>
              <div className={styles.field}>
                <label htmlFor={`${id}-code`} className="visually-hidden">{t('signin.codeLabel')}</label>
                <div className={styles.otp} data-shake={shake ? (shake % 2 ? 'a' : 'b') : undefined} data-error={codeError || locked ? true : undefined}>
                  <input
                    ref={codeRef}
                    id={`${id}-code`}
                    className={styles.otpInput}
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    pattern="[0-9]*"
                    maxLength={6}
                    value={code}
                    disabled={locked || expired}
                    readOnly={verifying}
                    onChange={(e) => onCodeChange(e.target.value)}
                    onFocus={() => setCodeFocused(true)}
                    onBlur={() => setCodeFocused(false)}
                    aria-invalid={codeError ? true : undefined}
                    aria-describedby={`${id}-code-status`}
                  />
                  {Array.from({ length: 6 }, (_, i) => (
                    <span key={i} className={styles.box} aria-hidden="true" data-active={codeFocused && (i === Math.min(code.length, 5)) || undefined} data-gap={i === 3 || undefined}>
                      {code[i] ?? ''}
                    </span>
                  ))}
                </div>
                <div id={`${id}-code-status`} aria-live="assertive" className={styles.codeStatus}>
                  {locked ? null : codeError ? <p className={styles.error}>{codeError}</p> : null}
                </div>
                {!expired && expiresAt ? <p className={styles.timer}>{t('signin.validFor', { time: formatClock((expiresAt - now) / 1000) })}</p> : null}
                {expired ? <p className={styles.error} role="status">{t('signin.expired')}</p> : null}
              </div>
              {locked ? (
                <Banner variant="danger" action={<ButtonLink href={HELPLINE} variant="call" icon={<Phone size={20} aria-hidden="true" />}>{t('common.call')}</ButtonLink>}>
                  {t('signin.locked')}
                </Banner>
              ) : null}
              <Button type="submit" size="lg" fullWidth disabled={code.length !== 6 || locked || expired} loading={verifying} loadingLabel={t('signin.checking')}>
                {t('signin.verify')}
              </Button>
              <Button variant={expired ? 'primary' : 'text'} size={expired ? 'lg' : 'md'} fullWidth={expired} disabled={resendIn > 0 || sending} loading={sending} loadingLabel={t('signin.sending')} onClick={() => void requestCode()}>
                {resendIn > 0 ? t('signin.resendIn', { time: formatClock(resendIn) }) : t('signin.resend')}
              </Button>
              {showNoCodeNotice ? (
                <Banner variant="info" action={<ButtonLink href={HELPLINE} variant="call" icon={<Phone size={20} aria-hidden="true" />}>{t('common.call')}</ButtonLink>}>
                  {t('signin.noCode')}
                </Banner>
              ) : (
                <p className={styles.fallback}>
                  {t('signin.noCode')} <a href={HELPLINE} className={styles.tel}>{t('signin.callHelpline')}</a>
                </p>
              )}
              <p className="visually-hidden" aria-live="polite">{announce}</p>
            </form>
          ) : null}

          {step === 'language' ? (
            <div className={styles.form}>
              <h1 ref={headingRef} tabIndex={-1} className={styles.h1}>{t('signin.languageTitle')}</h1>
              <LanguageRadioCards value={lang} onChange={setLang} legend={t('signin.languageTitle')} />
              {langError ? <p className={styles.error} role="alert">{langError}</p> : null}
              <Button size="lg" fullWidth loading={langSaving} loadingLabel={t('common.saving')} onClick={() => void continueLanguage()}>{t('signin.continue')}</Button>
            </div>
          ) : null}
        </div>
      </main>
    </div>
  );
}
