'use client';
import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { AskResponse, ChatMessage, ChatThreadDetail, SavedAnswer } from '@fasalalert/shared/api';
import { History, Pencil, Plus, RotateCcw, Trash2 } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { ButtonLink } from '@/components/UI/Button';
import { clientApi } from '@/lib/client-api';
import { KISAN_CALL_CENTRE } from '@/lib/config';
import { telHref } from '@/lib/format';
import { nowMs, useClientValue, useOnline } from '@/lib/hooks';
import { deletePendingQuestion, listPendingQuestions, savePendingQuestion } from '@/lib/offline';
import { cropLabel } from '@/lib/view';
import { Recorder, blobToBase64, recordingSupported } from '@/components/Voice/recorder';
import { ChatAnswer } from './ChatAnswer';
import { NEW_CHAT_EVENT, announceNewChat } from './ChatHistory';
import { useChats } from './ChatsProvider';
import { useHistorySheet } from './AskFrame';
import { Composer, type VoiceState } from './Composer';
import styles from './Chat.module.css';

const MAX_RECORDING_MS = 30_000;
const SLOW_S = 15;

interface Payload { text?: string; audio_b64?: string; audio_mime?: string; field_id?: number }
type Status = 'done' | 'thinking' | 'stopped' | 'error' | 'saved';
interface UiMessage {
  key: string;
  role: 'user' | 'assistant';
  content: string;
  spoken?: boolean;
  response?: SavedAnswer | null;
  status: Status;
  error?: 'network' | 'server' | 'limit';
  payload?: Payload;
  pendingId?: number | null;
}

function fromSaved(m: ChatMessage): UiMessage {
  return { key: `m${m.id}`, role: m.role, content: m.content, spoken: m.spoken, response: m.response, status: 'done' };
}

function newRequestId(): string {
  try { return crypto.randomUUID(); } catch { return `r${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`; }
}

function audioUrl(u: string | null | undefined): string | null {
  if (!u) return null;
  if (/^https?:\/\//.test(u)) return u;
  return u.replace(/^\/?api\/v1\//, '/api/proxy/');
}

/**
 * One conversation with the assistant (docs/UX_QA_AUDIT.md ASK-08, ASK-09). The first question creates the
 * conversation and the address becomes /ask/{id}. While an answer is being worked out the farmer can press Stop
 * (or Esc): the request is aborted and the server is told not to keep that question.
 */
export function ChatWorkspace({ initial, initialFieldId }: { initial: ChatThreadDetail | null; initialFieldId?: number | null }) {
  const { t, locale } = useI18n();
  const chats = useChats();
  const history = useHistorySheet();
  const online = useOnline();
  const [threadId, setThreadId] = useState<number | null>(initial?.id ?? null);
  const [title, setTitle] = useState(initial?.title ?? '');
  const [messages, setMessages] = useState<UiMessage[]>(() => (initial?.messages ?? []).map(fromSaved));
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [scope, setScope] = useState<number | null>(() => {
    const want = initialFieldId ?? initial?.field_id ?? null;
    return want !== null && chats.fields.some((f) => f.id === want) ? want : null;
  });
  const [voiceServer, setVoiceOk] = useState(chats.voiceAvailable);
  // Recording needs MediaRecorder, which only the browser can tell us about.
  const canRecord = useClientValue(recordingSupported, true);
  const voiceOk = voiceServer && canRecord;
  const [voice, setVoice] = useState<VoiceState>('idle');
  const [recSeconds, setRecSeconds] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  const [asksLeft, setAsksLeft] = useState<number | null>(null);
  const [speaking, setSpeaking] = useState<string | null>(null);
  const [hasVoice, setHasVoice] = useState(false);
  const threadRef = useRef(threadId);
  const inFlight = useRef(false);
  const current = useRef<{ controller: AbortController; requestId: string; key: string } | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const stick = useRef(true);
  const recorder = useRef<Recorder | null>(null);
  const recTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const focusInput = () => setTimeout(() => inputRef.current?.focus(), 30);
  const clearRecTimer = () => { if (recTimer.current) clearInterval(recTimer.current); recTimer.current = null; };

  const stopSpeaking = useCallback(() => {
    audioRef.current?.pause();
    audioRef.current = null;
    if (typeof speechSynthesis !== 'undefined') speechSynthesis.cancel();
    setSpeaking(null);
  }, []);

  const stop = useCallback(() => {
    const cur = current.current;
    if (!cur) return;
    current.current = null;
    cur.controller.abort();
    // Tell the server not to keep this question, even if its answer was saved a moment ago.
    void clientApi('ask/cancel', { method: 'POST', body: { request_id: cur.requestId } }).catch(() => undefined);
    setMessages((list) => list.map((m) => (m.key === cur.key ? { ...m, status: 'stopped' } : m)));
  }, []);

  // The browser may not know whether the device has a voice for this language until voices load.
  useEffect(() => {
    if (typeof speechSynthesis === 'undefined') return;
    const check = () => setHasVoice(speechSynthesis.getVoices().some((v) => v.lang.toLowerCase().startsWith(locale)));
    check();
    speechSynthesis.addEventListener?.('voiceschanged', check);
    return () => speechSynthesis.removeEventListener?.('voiceschanged', check);
  }, [locale]);

  // Questions saved on this phone while offline come back in a new conversation, ready to send.
  useEffect(() => {
    if (initial) return;
    let live = true;
    void listPendingQuestions().then((pending) => {
      if (!live || !pending.length) return;
      setMessages((list) => [...list, ...pending.flatMap((p, i): UiMessage[] => {
        const payload: Payload = { text: p.text, audio_b64: p.audio_b64, audio_mime: p.audio_mime, field_id: p.field_id };
        const shown = p.text ?? t('chat.spokenQuestion');
        return [
          { key: `pu${p.id ?? i}`, role: 'user', content: shown, spoken: Boolean(p.audio_b64), status: 'done', payload },
          { key: `pa${p.id ?? i}`, role: 'assistant', content: '', status: 'saved', payload, pendingId: p.id ?? null },
        ];
      })]);
    });
    return () => { live = false; };
  }, [initial, t]);

  // New conversation pressed while this page is already /ask: start over in place.
  useEffect(() => {
    if (initial) return;
    const reset = () => {
      stop();
      stopSpeaking();
      threadRef.current = null;
      setThreadId(null);
      setTitle('');
      setMessages([]);
      setNote(null);
      setText('');
      focusInput();
    };
    window.addEventListener(NEW_CHAT_EVENT, reset);
    return () => window.removeEventListener(NEW_CHAT_EVENT, reset);
  }, [initial, stop, stopSpeaking]);

  // Leaving the page stops whatever was running.
  useEffect(() => () => {
    current.current?.controller.abort();
    recorder.current?.cancel();
    if (recTimer.current) clearInterval(recTimer.current);
    stopSpeaking();
  }, [stopSpeaking]);

  // Seconds counter while an answer is being worked out.
  useEffect(() => {
    if (!busy) return;
    const start = nowMs();
    const iv = setInterval(() => setElapsed(Math.floor((nowMs() - start) / 1000)), 1000);
    return () => { clearInterval(iv); setElapsed(0); };
  }, [busy]);

  // Esc stops from anywhere on the page, not only from the text box.
  useEffect(() => {
    if (!busy) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); stop(); } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy, stop]);

  // Follow new messages unless the farmer scrolled up to read.
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const onScroll = () => { stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120; };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);
  useEffect(() => {
    const el = listRef.current;
    if (el && messages.length && stick.current) el.scrollTop = el.scrollHeight;
  }, [messages, busy]);

  const voiceFor = useCallback((): SpeechSynthesisVoice | null => {
    if (typeof speechSynthesis === 'undefined') return null;
    return speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith(locale)) ?? null;
  }, [locale]);

  const speak = useCallback((key: string, response: SavedAnswer, content: string) => {
    stopSpeaking();
    const url = audioUrl(response.answer_audio_url);
    if (url) {
      const a = new Audio(url);
      audioRef.current = a;
      a.onended = () => setSpeaking(null);
      void a.play().then(() => setSpeaking(key)).catch(() => setSpeaking(null));
      return;
    }
    const v = voiceFor();
    if (!v) return;
    const u = new SpeechSynthesisUtterance(content);
    u.voice = v;
    u.lang = v.lang;
    u.onend = () => setSpeaking(null);
    speechSynthesis.speak(u);
    setSpeaking(key);
  }, [stopSpeaking, voiceFor]);

  const send = useCallback(async (payload: Payload, shown: string, spoken: boolean) => {
    if (inFlight.current) return;
    const stamp = `${Date.now()}`;
    const userKey = `u${stamp}`;
    const aiKey = `a${stamp}`;
    const fieldId = payload.field_id ?? scope ?? undefined;
    const body = { ...payload, field_id: fieldId };
    stopSpeaking();
    setNote(null);
    stick.current = true;

    const saveForLater = async (key: string) => {
      const pid = await savePendingQuestion({ ...body, locale, savedAt: new Date().toISOString() });
      setMessages((list) => list.map((m) => (m.key === key ? { ...m, status: 'saved', pendingId: pid } : m)));
    };

    if (!navigator.onLine) {
      setMessages((list) => [...list,
        { key: userKey, role: 'user', content: shown, spoken, status: 'done', payload: body },
        { key: aiKey, role: 'assistant', content: '', status: 'thinking', payload: body }]);
      await saveForLater(aiKey);
      return;
    }

    inFlight.current = true;
    setBusy(true);
    const requestId = newRequestId();
    const controller = new AbortController();
    current.current = { controller, requestId, key: aiKey };
    setMessages((list) => [...list,
      { key: userKey, role: 'user', content: shown, spoken, status: 'done', payload: body },
      { key: aiKey, role: 'assistant', content: '', status: 'thinking', payload: body }]);
    const patch = (key: string, p: Partial<UiMessage>) => setMessages((list) => list.map((m) => (m.key === key ? { ...m, ...p } : m)));
    try {
      const r = await clientApi<AskResponse>('ask', {
        method: 'POST', signal: controller.signal,
        body: { ...body, locale, thread_id: threadRef.current ?? undefined, request_id: requestId },
      });
      if (current.current?.requestId !== requestId) return; // stopped while the reply was on its way
      if (!r.ok) {
        if (r.kind === 'network' || (r.status === 503 && r.error?.details?.reason === 'upstream_unreachable')) { await saveForLater(aiKey); return; }
        const limit = r.status === 429 || r.error?.code === 'rate_limited';
        if (limit) setAsksLeft(0);
        patch(aiKey, { status: 'error', error: limit ? 'limit' : 'server' });
        return;
      }
      const res = r.data;
      if (res.cancelled) { patch(aiKey, { status: 'stopped' }); return; }
      if (typeof res.asks_remaining === 'number') setAsksLeft(res.asks_remaining);
      if (res.intent === 'stt_unavailable' || res.stt_available === false) setVoiceOk(false);
      if (res.intent === 'stt_unavailable' || res.intent === 'no_speech') {
        setMessages((list) => list.filter((m) => m.key !== userKey && m.key !== aiKey));
        setNote(res.intent === 'no_speech' ? t('chat.noSpeech') : t('chat.voiceOff'));
        return;
      }
      const saved: SavedAnswer = res.assistant_message?.response ?? res;
      const finalAiKey = res.assistant_message ? `m${res.assistant_message.id}` : aiKey;
      setMessages((list) => list.map((m) => {
        if (m.key === userKey) return { ...m, key: res.user_message ? `m${res.user_message.id}` : m.key, content: res.transcript || m.content };
        if (m.key === aiKey) return { ...m, key: finalAiKey, content: res.answer, response: saved, status: 'done' };
        return m;
      }));
      if (res.thread_id) {
        const at = res.assistant_message?.created_at ?? new Date().toISOString();
        const snippet = res.answer.slice(0, 160);
        if (!threadRef.current) {
          threadRef.current = res.thread_id;
          setThreadId(res.thread_id);
          setTitle(res.thread_title ?? shown);
          // The conversation now has an address of its own, so reload and Back keep it.
          window.history.replaceState(window.history.state, '', `/${locale}/ask/${res.thread_id}`);
          chats.upsert({ id: res.thread_id, title: res.thread_title ?? shown, last_activity_at: at, created_at: at, message_count: 2, snippet, field_id: fieldId ?? null });
        } else {
          const existing = chats.threads.find((x) => x.id === res.thread_id);
          chats.upsert({ id: res.thread_id, last_activity_at: at, snippet, message_count: (existing?.message_count ?? 0) + 2 });
        }
      }
      if (spoken && (audioUrl(res.answer_audio_url) || voiceFor())) speak(finalAiKey, saved, res.answer);
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') patch(aiKey, { status: 'stopped' });
      else patch(aiKey, { status: 'error', error: 'server' });
    } finally {
      if (current.current?.requestId === requestId) current.current = null;
      inFlight.current = false;
      setBusy(false);
    }
  }, [chats, locale, scope, speak, stopSpeaking, t, voiceFor]);

  const sendText = () => {
    const question = text.trim();
    if (!question || busy) return;
    setText('');
    void send({ text: question }, question, false);
  };

  /* ---------- after Stop, an error or an offline save: ask again, edit, or discard ---------- */
  const questionFor = (ai: UiMessage) => {
    const i = messages.findIndex((m) => m.key === ai.key);
    return i > 0 ? messages[i - 1] : undefined;
  };
  const dropPair = (ai: UiMessage, q: UiMessage | undefined) => {
    if (ai.pendingId) void deletePendingQuestion(ai.pendingId);
    setMessages((list) => list.filter((m) => m.key !== ai.key && m.key !== q?.key));
  };
  const retry = (ai: UiMessage) => {
    const q = questionFor(ai);
    if (!q?.payload) return;
    dropPair(ai, q);
    void send(q.payload, q.content, Boolean(q.spoken));
  };
  /** Put the question back in the box. For an answer that was heard unclearly, the heard words go back. */
  const edit = (ai: UiMessage) => {
    const q = questionFor(ai);
    if (!q) return;
    if (ai.status === 'done') {
      setText(ai.response?.transcript || q.content);
    } else {
      dropPair(ai, q);
      setText(q.payload?.text ?? '');
    }
    focusInput();
  };

  /* ---------- voice ---------- */
  const finishRecording = async (sendIt: boolean) => {
    const rec = recorder.current;
    recorder.current = null;
    clearRecTimer();
    if (!rec) { setVoice('idle'); return; }
    if (!sendIt) { rec.cancel(); setVoice('idle'); focusInput(); return; }
    setVoice('sending');
    const out = await rec.stop();
    if (!out || out.durationMs < 400 || out.blob.size === 0) { setVoice('idle'); setNote(t('chat.noSpeech')); return; }
    const b64 = await blobToBase64(out.blob);
    setVoice('idle');
    void send({ audio_b64: b64, audio_mime: out.mime }, t('chat.spokenQuestion'), true);
  };
  const startRecording = async () => {
    if (!voiceOk || busy || recorder.current) return;
    stopSpeaking();
    setNote(null);
    setVoice('starting');
    const rec = new Recorder();
    recorder.current = rec;
    const result = await rec.start();
    if (recorder.current !== rec) { rec.cancel(); return; } // cancelled while the microphone was opening
    if (result !== 'ok') {
      recorder.current = null;
      setVoice('idle');
      setNote(result === 'denied' ? t('ask.mic.denied') : result === 'timeout' ? t('ask.mic.notResponding') : t('ask.mic.unsupported'));
      return;
    }
    setVoice('recording');
    setRecSeconds(0);
    recTimer.current = setInterval(() => {
      const ms = rec.elapsedMs();
      setRecSeconds(Math.floor(ms / 1000));
      if (ms >= MAX_RECORDING_MS) void finishRecording(true);
    }, 250);
  };

  const promptCrop = (scope !== null ? chats.fields.find((f) => f.id === scope)?.crop : chats.fields[0]?.crop) ?? null;
  const prompts = promptCrop
    ? ['frost', 'rain', 'stage', 'pest', 'price'].map((k) => t(`ask.suggest.${k}`, { crop: cropLabel(t, promptCrop, true) }))
    : [t('ask.prompt1'), t('ask.prompt2'), t('ask.prompt3')];
  const lastAi = [...messages].reverse().find((m) => m.role === 'assistant');
  const kvk = chats.kvk;
  const composerNote = note
    ?? (!online ? t('chat.offline')
      : asksLeft === 0 ? t('chat.error.limit')
        : asksLeft !== null && asksLeft <= 5 ? t('chat.asksLeft', { count: asksLeft }) : null);

  return (
    <div className={styles.workspace}>
      <header className={styles.head}>
        <button type="button" className={styles.headBtn} data-mobile onClick={history.open} aria-haspopup="dialog">
          <History size={20} aria-hidden="true" /><span>{t('chat.history')}</span>
        </button>
        <h1 className={styles.title}>{title || t('chat.newConversation')}</h1>
        {threadId || messages.length ? (
          <Link href={`/${locale}/ask`} className={styles.headBtn} onClick={() => announceNewChat()}>
            <Plus size={20} aria-hidden="true" /><span>{t('chat.new')}</span>
          </Link>
        ) : null}
      </header>

      <div className={styles.scroll} ref={listRef}>
        <div className={styles.thread}>
          {messages.length === 0 ? (
            <div className={styles.welcome}>
              <h2 className={styles.welcomeTitle}>{t('chat.welcome.title')}</h2>
              <p className={styles.welcomeBody}>{t('chat.welcome.body')}</p>
              <ul className={styles.starters} aria-label={t('ask.promptsLabel')}>
                {prompts.map((p) => (
                  <li key={p}>
                    {/* A suggestion fills the box and waits for Send, so a tap never asks by accident (PRD §7.5). */}
                    <button type="button" className={styles.starter} onClick={() => { setText(p); focusInput(); }}>{p}</button>
                  </li>
                ))}
              </ul>
              {!voiceOk ? <p className={styles.welcomeNote}>{t('ask.mic.sttUnavailable')}</p> : null}
            </div>
          ) : null}
          {messages.map((m) => (m.role === 'user' ? (
            <div key={m.key} className={styles.userRow}>
              <span className="visually-hidden">{t('chat.you')}</span>
              <div className={styles.userBubble} data-spoken={m.spoken || undefined}>{m.content}</div>
            </div>
          ) : (
            <div key={m.key} className={styles.aiRow}>
              <span className="visually-hidden">{t('chat.assistant')}</span>
              {m.status === 'thinking' ? (
                <div className={styles.thinking} role="status">
                  <span className={styles.dots} aria-hidden="true"><i /><i /><i /></span>
                  <span>{m.payload?.audio_b64 ? t('chat.listening', { seconds: elapsed }) : t('chat.thinking', { seconds: elapsed })}</span>
                  {elapsed >= SLOW_S ? <span className={styles.slow}>{t('chat.thinkingSlow')}</span> : null}
                </div>
              ) : m.status === 'done' && m.response ? (
                <>
                  {m.response.intent === 'confirm_transcript' ? (
                    <div className={styles.heard}>
                      <span>{t('chat.notSure')}</span>
                      <button type="button" className={styles.linkBtn} onClick={() => edit(m)}><Pencil size={16} aria-hidden="true" /> {t('chat.fixQuestion')}</button>
                    </div>
                  ) : null}
                  <ChatAnswer response={m.response} content={m.content} speaking={speaking === m.key}
                    canSpeak={Boolean(audioUrl(m.response.answer_audio_url)) || hasVoice}
                    onListen={() => speak(m.key, m.response!, m.content)} onStopListening={stopSpeaking} />
                </>
              ) : (
                <div className={styles.problem} data-kind={m.status} role="status">
                  <p>{m.status === 'stopped' ? t('chat.stopped')
                    : m.status === 'saved' ? t('chat.savedOffline')
                      : m.error === 'limit' ? t('chat.error.limit')
                        : m.error === 'network' ? t('chat.error.network') : t('chat.error.server')}</p>
                  {m.error === 'limit' ? (
                    <ButtonLink href={telHref(kvk?.phone ?? KISAN_CALL_CENTRE)} variant="call">
                      {kvk ? t('abstain.callKvk', { name: kvk.name }) : t('settings.help.kcc', { phone: KISAN_CALL_CENTRE })}
                    </ButtonLink>
                  ) : m.status === 'saved' ? (
                    <div className={styles.problemActions}>
                      <button type="button" className={styles.actionBtn} onClick={() => retry(m)} disabled={busy || !online}><RotateCcw size={16} aria-hidden="true" /> {t('chat.sendNow')}</button>
                      <button type="button" className={styles.actionBtn} onClick={() => dropPair(m, questionFor(m))}><Trash2 size={16} aria-hidden="true" /> {t('chat.discard')}</button>
                    </div>
                  ) : m.key === lastAi?.key ? (
                    <div className={styles.problemActions}>
                      {questionFor(m)?.payload?.text ? (
                        <button type="button" className={styles.actionBtn} onClick={() => edit(m)} disabled={busy}><Pencil size={16} aria-hidden="true" /> {t('chat.editResend')}</button>
                      ) : null}
                      <button type="button" className={styles.actionBtn} onClick={() => retry(m)} disabled={busy}><RotateCcw size={16} aria-hidden="true" /> {t('chat.askAgain')}</button>
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          )))}
        </div>
      </div>

      <Composer inputRef={inputRef} text={text} onText={setText} busy={busy} onSend={sendText} onStop={stop}
        scope={scope} onScope={setScope} fields={chats.fields} voiceAvailable={voiceOk}
        voice={voice} seconds={recSeconds} onMic={() => void startRecording()} onMicSend={() => void finishRecording(true)} onMicCancel={() => void finishRecording(false)}
        note={composerNote} />
    </div>
  );
}
