'use client';
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import type { ChatThreadPage, ChatThreadSummary, Crop } from '@fasalalert/shared/api';
import { upsertThread } from '@/lib/chat-groups';
import { clientApi } from '@/lib/client-api';

export interface ChatField { id: number; name: string; crop: Crop }

interface ChatsValue {
  threads: ChatThreadSummary[];
  hasMore: boolean;
  loadingMore: boolean;
  upsert: (patch: Partial<ChatThreadSummary> & { id: number }) => void;
  remove: (id: number) => void;
  loadMore: () => Promise<void>;
  /** What the conversation pages need from the account, loaded once by the layout. */
  fields: ChatField[];
  kvk: { name: string; phone: string } | null;
  voiceAvailable: boolean;
  historyFailed: boolean;
}

const ChatsContext = createContext<ChatsValue | null>(null);

/** The conversation list shared by the history panel and the conversation, so a new chat appears at once. */
export function ChatsProvider({ initial, historyFailed, fields, kvk, voiceAvailable, children }: {
  initial: ChatThreadPage; historyFailed: boolean; fields: ChatField[]; kvk: ChatsValue['kvk']; voiceAvailable: boolean; children: ReactNode;
}) {
  const [threads, setThreads] = useState(initial.items);
  const [cursor, setCursor] = useState(initial.next_cursor);
  const [loadingMore, setLoadingMore] = useState(false);

  const upsert = useCallback<ChatsValue['upsert']>((patch) => setThreads((list) => upsertThread(list, patch)), []);
  const remove = useCallback((id: number) => setThreads((list) => list.filter((t) => t.id !== id)), []);
  const loadMore = useCallback(async () => {
    if (!cursor) return;
    setLoadingMore(true);
    const r = await clientApi<ChatThreadPage>('ask/threads', { query: { cursor } });
    setLoadingMore(false);
    if (!r.ok) return;
    setThreads((list) => [...list, ...r.data.items.filter((t) => !list.some((x) => x.id === t.id))]);
    setCursor(r.data.next_cursor);
  }, [cursor]);

  const value = useMemo(() => ({ threads, hasMore: Boolean(cursor), loadingMore, upsert, remove, loadMore, fields, kvk, voiceAvailable, historyFailed }),
    [threads, cursor, loadingMore, upsert, remove, loadMore, fields, kvk, voiceAvailable, historyFailed]);
  return <ChatsContext.Provider value={value}>{children}</ChatsContext.Provider>;
}

export function useChats(): ChatsValue {
  const v = useContext(ChatsContext);
  if (!v) throw new Error('useChats outside ChatsProvider');
  return v;
}
