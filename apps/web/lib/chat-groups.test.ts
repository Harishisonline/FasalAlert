import { describe, expect, it } from 'vitest';
import type { ChatThreadSummary } from '@fasalalert/shared/api';
import { groupThreads, upsertThread } from './chat-groups';

const t = (id: number, at: string, pinned = false): ChatThreadSummary => ({
  id, title: `Chat ${id}`, pinned, field_id: null, created_at: at, last_activity_at: at, message_count: 2, snippet: '',
});

describe('groupThreads (ASK-08)', () => {
  // 10:00 IST on 16 Nov 2026.
  const now = new Date('2026-11-16T04:30:00Z');

  it('puts saved first, then IST day buckets in order, and drops empty groups', () => {
    const groups = groupThreads([
      t(1, '2026-11-16T03:00:00Z'), // 08:30 IST today
      t(2, '2026-11-15T19:00:00Z'), // 00:30 IST on the 16th, still today in IST
      t(3, '2026-11-15T10:00:00Z'), // yesterday
      t(4, '2026-11-11T10:00:00Z'), // within 7 days
      t(5, '2026-10-25T10:00:00Z'), // within 30 days
      t(6, '2026-08-01T10:00:00Z'), // older
      t(7, '2026-08-01T10:00:00Z', true), // saved wins over age
    ], now);
    expect(groups.map((g) => g.id)).toEqual(['saved', 'today', 'yesterday', 'week', 'month', 'older']);
    expect(groups[0]!.threads.map((x) => x.id)).toEqual([7]);
    expect(groups[1]!.threads.map((x) => x.id)).toEqual([1, 2]);
    expect(groups.find((g) => g.id === 'older')!.threads.map((x) => x.id)).toEqual([6]);
  });

  it('returns no groups for no conversations', () => {
    expect(groupThreads([], now)).toEqual([]);
  });
});

describe('upsertThread', () => {
  const list = [t(1, '2026-11-16T03:00:00Z'), t(2, '2026-11-15T03:00:00Z')];

  it('adds a new conversation at the top with defaults', () => {
    const next = upsertThread(list, { id: 9, title: 'Frost tonight?' });
    expect(next.map((x) => x.id)).toEqual([9, 1, 2]);
    expect(next[0]).toMatchObject({ title: 'Frost tonight?', pinned: false, message_count: 0 });
  });

  it('moves a conversation to the top when it has new activity', () => {
    const next = upsertThread(list, { id: 2, last_activity_at: '2026-11-16T05:00:00Z' });
    expect(next.map((x) => x.id)).toEqual([2, 1]);
  });

  it('keeps its place on rename or save', () => {
    const next = upsertThread(list, { id: 2, title: 'Renamed', pinned: true });
    expect(next.map((x) => x.id)).toEqual([1, 2]);
    expect(next[1]).toMatchObject({ title: 'Renamed', pinned: true });
  });
});
