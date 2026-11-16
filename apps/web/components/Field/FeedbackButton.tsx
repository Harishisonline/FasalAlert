'use client';
import { useState } from 'react';
import { ThumbsDown } from '@/components/Icon';
import { useT } from '@/components/I18n';
import { clientApi } from '@/lib/client-api';
import styles from './FeedbackButton.module.css';

/** "Not useful": POST /alerts/{id}/feedback {value: -1} (PRD §7.4). */
export function FeedbackButton({ alertId, initial }: { alertId: number; initial: -1 | 1 | null }) {
  const t = useT();
  const [state, setState] = useState<'idle' | 'saving' | 'done' | 'error'>(initial === -1 ? 'done' : 'idle');
  const send = async () => {
    setState('saving');
    const r = await clientApi(`alerts/${alertId}/feedback`, { method: 'POST', body: { value: -1 } });
    setState(r.ok ? 'done' : 'error');
  };
  return (
    <span className={styles.wrap}>
      <button type="button" className={styles.button} aria-pressed={state === 'done'} disabled={state === 'done' || state === 'saving'} onClick={() => void send()}>
        <ThumbsDown size={20} aria-hidden="true" />
        {t('field.history.notUseful')}
      </button>
      <span role="status" className={styles.status}>
        {state === 'done' ? t('field.history.markedNotUseful') : state === 'error' ? t('common.saveFailed') : ''}
      </span>
    </span>
  );
}
