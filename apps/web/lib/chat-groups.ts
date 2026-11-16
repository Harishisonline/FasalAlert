/** Conversation history groups: Saved first, then Today, Yesterday, Previous 7 days, Previous 30 days, Older (IST days). */
import type { ChatThreadSummary } from '@fasalalert/shared/api';
import { istDateKey } from './format';

export type ChatGroupId = 'saved' | 'today' | 'yesterday' | 'week' | 'month' | 'older';
export interface ChatGroup { id: ChatGroupId; threads: ChatThreadSummary[] }

const ORDER: ChatGroupId[] = ['saved', 'today', 'yesterday', 'week', 'month', 'older'];
const DAY = 86_400_000;

export function groupThreads(threads: ChatThreadSummary[], now: Date = new Date()): ChatGroup[] {
  const today = istDateKey(now);
  const yesterday = istDateKey(new Date(now.getTime() - DAY));
  const week = now.getTime() - 7 * DAY;
  const month = now.getTime() - 30 * DAY;
  const by = new Map<ChatGroupId, ChatThreadSummary[]>(ORDER.map((id) => [id, []]));
  for (const t of threads) {
    if (t.pinned) { by.get('saved')!.push(t); continue; }
    const at = new Date(t.last_activity_at);
    const key = istDateKey(at);
    const id: ChatGroupId = key === today ? 'today' : key === yesterday ? 'yesterday' : at.getTime() > week ? 'week' : at.getTime() > month ? 'month' : 'older';
    by.get(id)!.push(t);
  }
  return ORDER.map((id) => ({ id, threads: by.get(id)! })).filter((g) => g.threads.length > 0);
}

/** Put a changed or new conversation in the list: new activity moves it to the top, a rename or save keeps its place. */
export function upsertThread(list: ChatThreadSummary[], patch: Partial<ChatThreadSummary> & { id: number }): ChatThreadSummary[] {
  const existing = list.find((t) => t.id === patch.id);
  const now = new Date().toISOString();
  const merged: ChatThreadSummary = {
    title: '', pinned: false, field_id: null, created_at: now, last_activity_at: now, message_count: 0, snippet: '',
    ...existing, ...patch,
  };
  if (!existing || (patch.last_activity_at && patch.last_activity_at !== existing.last_activity_at)) {
    return [merged, ...list.filter((t) => t.id !== patch.id)];
  }
  return list.map((t) => (t.id === patch.id ? merged : t));
}
