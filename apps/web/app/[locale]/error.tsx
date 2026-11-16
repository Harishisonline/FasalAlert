'use client';
import { useEffect, useRef, useState } from 'react';
import { TriangleAlert } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { PageMain } from '@/components/Layout/Page';
import { Button, ButtonLink } from '@/components/UI/Button';
import styles from '@/components/System/System.module.css';

/**
 * R11 error boundary (PRD §7.11, design.md 12.12): a friendly message, the error code for support and
 * a retry. Never a stack trace. Neutral colours: the user is not at fault.
 */
export default function LocaleError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const { t, locale } = useI18n();
  const heading = useRef<HTMLHeadingElement>(null);
  const [tries, setTries] = useState(0);
  const [trying, setTrying] = useState(false);
  const [copied, setCopied] = useState(false);
  const code = (error as Error & { traceId?: string }).traceId ?? error.digest ?? '';
  useEffect(() => { heading.current?.focus(); document.title = `${t('error.title')} · FasalAlert`; }, [t]);
  return (
    <>
      <PageMain width="narrow">
        <div className={styles.system}>
          <TriangleAlert size={48} aria-hidden="true" className={styles.icon} />
          <h1 ref={heading} tabIndex={-1} className={styles.title}>{t('error.title')}</h1>
          <p className={styles.body}>{t('error.body')}</p>
          <div className={styles.actions}>
            <Button size="lg" fullWidth loading={trying} loadingLabel={t('common.tryingAgain')}
              onClick={() => { setTrying(true); setTries((n) => n + 1); setTimeout(() => { setTrying(false); reset(); }, 50); }}>
              {t('common.tryAgain')}
            </Button>
            <ButtonLink href={`/${locale}/home`} variant="secondary" size="lg" fullWidth>{t('error.goHome')}</ButtonLink>
          </div>
          {tries >= 2 ? <p className={styles.body}>{t('error.persist')}</p> : null}
          {code ? (
            <p className={styles.code}>
              <span>{t('state.errorCode', { code })}</span>
              <Button variant="text" onClick={() => { void navigator.clipboard?.writeText(code).then(() => setCopied(true)); }}>{copied ? t('common.copied') : t('common.copy')}</Button>
              <span className="visually-hidden" aria-live="polite">{copied ? t('common.copied') : ''}</span>
            </p>
          ) : null}
        </div>
      </PageMain>
    </>
  );
}
