'use client';
import { useState } from 'react';
import type { AbstainReason, SavedAnswer } from '@fasalalert/shared/api';
import { Check, Copy, Square, Volume2 } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { AbstainNotice } from '@/components/Risk/AbstainNotice';
import { SourceLine } from '@/components/Risk/SourceLine';
import { fromSourceRef } from '@/lib/view';
import styles from './Chat.module.css';

/**
 * One answer: the text, the facts taken from the farmer's own field data, the sources, and Listen and Copy.
 * An abstention says why and offers the KVK call; facts found before abstaining are still shown (ASK-06).
 */
export function ChatAnswer({ response, content, speaking, canSpeak, onListen, onStopListening }: {
  response: SavedAnswer; content: string; speaking: boolean; canSpeak: boolean; onListen: () => void; onStopListening: () => void;
}) {
  const { t, locale } = useI18n();
  const [copied, setCopied] = useState(false);
  const now = new Date();
  const cards = response.cards ?? [];
  const sources = response.sources ?? [];
  const abstainOnly = Boolean(response.abstain) && cards.length === 0;
  return (
    <div className={styles.answer}>
      {!abstainOnly && content ? <p className={styles.answerText}>{content}</p> : null}
      {cards.length ? (
        <div className={styles.facts}>
          <p className={styles.factsTitle}>{t('chat.answer.facts')}</p>
          <dl className={styles.factList}>
            {cards.map((c, i) => (
              <div key={`${c.label}-${i}`}><dt>{c.label}</dt><dd>{c.value}</dd></div>
            ))}
          </dl>
        </div>
      ) : null}
      {response.abstain ? (
        <AbstainNotice reason={(response.abstain_reason ?? 'no_retrieval_above_threshold') as AbstainReason} kvk={response.kvk ?? null} t={t} locale={locale} now={now} variant="compact" />
      ) : null}
      {sources.length ? (
        <div className={styles.answerSources}>
          <p className={styles.factsTitle}>{t('chat.answer.sources')}</p>
          <SourceLine sources={sources.map((s) => fromSourceRef(s))} t={t} locale={locale} now={now} compact />
        </div>
      ) : null}
      <div className={styles.answerActions}>
        {speaking ? (
          <button type="button" className={styles.actionBtn} onClick={onStopListening}><Square size={16} aria-hidden="true" /> {t('chat.answer.stopListening')}</button>
        ) : canSpeak ? (
          <button type="button" className={styles.actionBtn} onClick={onListen}><Volume2 size={16} aria-hidden="true" /> {t('chat.answer.listen')}</button>
        ) : null}
        <button type="button" className={styles.actionBtn} onClick={() => {
          void navigator.clipboard?.writeText(content).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); });
        }}>
          {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />} {copied ? t('chat.answer.copied') : t('chat.answer.copy')}
        </button>
      </div>
    </div>
  );
}
