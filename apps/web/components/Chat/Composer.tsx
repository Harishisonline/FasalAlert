'use client';
import { useEffect, useId, type RefObject } from 'react';
import { ArrowUp, Mic, Square, X } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import type { ChatField } from './ChatsProvider';
import styles from './Chat.module.css';

export const MAX_QUESTION = 500; // the API's limit (schemas/bodies.py AskBody.text)

export type VoiceState = 'idle' | 'starting' | 'recording' | 'sending';

/**
 * Question box (docs/UX_QA_AUDIT.md ASK-09): grows with the text; Enter sends on a keyboard, Shift+Enter adds a
 * line; while an answer is being worked out the Send button becomes Stop (Esc stops too).
 */
export function Composer({ inputRef, text, onText, busy, onSend, onStop, scope, onScope, fields, voiceAvailable, voice, seconds, onMic, onMicSend, onMicCancel, note }: {
  inputRef: RefObject<HTMLTextAreaElement | null>; text: string; onText: (v: string) => void; busy: boolean; onSend: () => void; onStop: () => void;
  scope: number | null; onScope: (id: number | null) => void; fields: ChatField[]; voiceAvailable: boolean;
  voice: VoiceState; seconds: number; onMic: () => void; onMicSend: () => void; onMicCancel: () => void; note: string | null;
}) {
  const { t } = useI18n();
  const id = useId();

  // Grow with the text up to a limit, so a long question stays readable while typing.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text, inputRef]);

  const recording = voice === 'recording' || voice === 'starting';
  return (
    <div className={styles.composerWrap}>
      <form className={styles.composer} data-busy={busy || undefined} onSubmit={(e) => { e.preventDefault(); if (!busy) onSend(); }}>
        {recording ? (
          <div className={styles.recording} role="status">
            <span className={styles.recDot} aria-hidden="true" />
            <span>{voice === 'starting' ? t('chat.composer.micStarting') : t('chat.composer.recording', { seconds })}</span>
          </div>
        ) : (
          <>
            <label htmlFor={`${id}-q`} className="visually-hidden">{t('chat.composer.label')}</label>
            <textarea id={`${id}-q`} ref={inputRef} rows={1} value={text} maxLength={MAX_QUESTION} disabled={voice === 'sending'}
              placeholder={t('chat.composer.placeholder')}
              onChange={(e) => onText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape' && busy) { e.preventDefault(); onStop(); return; }
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && window.matchMedia('(pointer: fine)').matches) {
                  e.preventDefault();
                  if (!busy) onSend();
                }
              }} />
          </>
        )}
        <div className={styles.composerBar}>
          <label className={styles.scope}>
            <span className={styles.scopeLabel}>{t('chat.composer.scope')}</span>
            <select value={scope ?? ''} disabled={busy} onChange={(e) => onScope(e.target.value ? Number(e.target.value) : null)}>
              <option value="">{t('chat.composer.allFields')}</option>
              {fields.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
          </label>
          <div className={styles.composerActions}>
            {text.length > MAX_QUESTION - 80 ? <span className={styles.count} aria-live="polite">{MAX_QUESTION - text.length}</span> : null}
            {recording ? (
              <>
                <button type="button" className={styles.iconBtn} onClick={onMicCancel} aria-label={t('chat.composer.micCancel')} title={t('chat.composer.micCancel')}>
                  <X size={20} aria-hidden="true" />
                </button>
                <button type="button" className={styles.send} onClick={onMicSend} disabled={voice === 'starting'} aria-label={t('chat.composer.micSend')} title={t('chat.composer.micSend')}>
                  <Square size={16} aria-hidden="true" />
                </button>
              </>
            ) : (
              <>
                <button type="button" className={styles.iconBtn} onClick={onMic} disabled={busy || !voiceAvailable || voice === 'sending'}
                  aria-label={voiceAvailable ? t('chat.composer.speak') : t('chat.composer.voiceOff')} title={voiceAvailable ? t('chat.composer.speak') : t('chat.composer.voiceOff')}>
                  <Mic size={20} aria-hidden="true" />
                </button>
                {busy ? (
                  <button type="button" className={styles.stop} onClick={onStop} aria-label={t('chat.composer.stop')} title={t('chat.composer.stopHint')}>
                    <Square size={16} aria-hidden="true" />
                  </button>
                ) : (
                  <button type="submit" className={styles.send} disabled={!text.trim()} aria-label={t('chat.composer.send')} title={t('chat.composer.send')}>
                    <ArrowUp size={20} aria-hidden="true" />
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      </form>
      <p className={styles.composerNote} aria-live="polite">{note ?? t('chat.composer.hint')}</p>
    </div>
  );
}
