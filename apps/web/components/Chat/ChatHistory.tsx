'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChatThreadPage, ChatThreadSummary } from '@fasalalert/shared/api';
import { BadgeCheck, Ellipsis, Pencil, Plus, Search, Trash2 } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { Button } from '@/components/UI/Button';
import { Dialog } from '@/components/UI/Dialog';
import { useToast } from '@/components/UI/Toast';
import { groupThreads } from '@/lib/chat-groups';
import { clientApi } from '@/lib/client-api';
import { useChats } from './ChatsProvider';
import styles from './Chat.module.css';

export const NEW_CHAT_EVENT = 'fasalalert:new-chat';

/** Start a new conversation, also when the URL is already /ask (the page then resets in place). */
export function announceNewChat(): void {
  window.dispatchEvent(new Event(NEW_CHAT_EVENT));
}

/**
 * The conversation history (docs/UX_QA_AUDIT.md ASK-08): New conversation, search across titles and messages,
 * then Saved, Today, Yesterday, Previous 7 days, Previous 30 days and Older, each with rename, save and delete.
 */
export function ChatHistory({ activeId, onNavigate }: { activeId: number | null; onNavigate?: () => void }) {
  const { t, locale } = useI18n();
  const { threads, hasMore, loadingMore, loadMore, historyFailed } = useChats();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<ChatThreadSummary[] | null>(null);
  const [searching, setSearching] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef(0);
  const groups = useMemo(() => groupThreads(results ?? threads), [results, threads]);

  const onSearch = (value: string) => {
    setQuery(value);
    if (timer.current) clearTimeout(timer.current);
    const seq = ++latest.current; // a slower, older search never overwrites a newer one
    if (!value.trim()) { setResults(null); setSearching(false); return; }
    setSearching(true);
    timer.current = setTimeout(async () => {
      const r = await clientApi<ChatThreadPage>('ask/threads', { query: { q: value.trim(), limit: 50 } });
      if (seq !== latest.current) return;
      setResults(r.ok ? r.data.items : []);
      setSearching(false);
    }, 300);
  };
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  return (
    <div className={styles.history}>
      <Link href={`/${locale}/ask`} className={styles.newChat} onClick={() => { announceNewChat(); onNavigate?.(); }}>
        <Plus size={20} aria-hidden="true" /> {t('chat.newConversation')}
      </Link>
      <label className={styles.historySearch}>
        <Search size={18} aria-hidden="true" />
        <span className="visually-hidden">{t('chat.search')}</span>
        <input type="search" value={query} onChange={(e) => onSearch(e.target.value)} placeholder={t('chat.search')} autoComplete="off" />
      </label>
      <div className={styles.historyList} aria-busy={searching || undefined}>
        {historyFailed && results === null ? <p className={styles.historyNote} role="status">{t('chat.historyFailed')}</p> : null}
        {results !== null && results.length === 0 && !searching ? <p className={styles.historyNote}>{t('chat.noMatches', { query: query.trim() })}</p> : null}
        {results === null && threads.length === 0 && !historyFailed ? <p className={styles.historyNote}>{t('chat.empty')}</p> : null}
        {groups.map((g) => (
          <section key={g.id} className={styles.group} aria-labelledby={`chat-g-${g.id}`}>
            <h2 id={`chat-g-${g.id}`} className={styles.groupLabel}>{t(`chat.groups.${g.id}`)}</h2>
            <ul>
              {g.threads.map((c) => <HistoryItem key={c.id} thread={c} active={c.id === activeId} onNavigate={onNavigate} />)}
            </ul>
          </section>
        ))}
        {results === null && hasMore ? (
          <button type="button" className={styles.loadMore} disabled={loadingMore} onClick={() => void loadMore()}>
            {loadingMore ? t('state.loading') : t('chat.showOlder')}
          </button>
        ) : null}
      </div>
    </div>
  );
}

function HistoryItem({ thread, active, onNavigate }: { thread: ChatThreadSummary; active: boolean; onNavigate?: () => void }) {
  const { t, locale } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const { upsert, remove } = useChats();
  const [menu, setMenu] = useState<{ top: number; left: number } | null>(null);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(thread.title);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const moreRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menu) return;
    const close = (e: Event) => { if (!(e.target instanceof Node) || !menuRef.current?.contains(e.target)) setMenu(null); };
    // The menu is placed against the viewport, so it closes only when something that moves its button scrolls
    // (the history list or the page), not when the conversation beside it scrolls.
    const onScroll = (e: Event) => { if (e.target instanceof Node && moreRef.current && e.target.contains(moreRef.current)) setMenu(null); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setMenu(null); moreRef.current?.focus(); } };
    document.addEventListener('pointerdown', close);
    document.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', close);
    document.addEventListener('keydown', onKey);
    menuRef.current?.querySelector('button')?.focus({ preventScroll: true });
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [menu]);

  // The list scrolls, so the menu is placed against the viewport and opens upwards near the bottom.
  const openMenu = () => {
    const r = moreRef.current?.getBoundingClientRect();
    if (!r) return;
    const height = 168;
    const top = r.bottom + height > window.innerHeight - 8 ? r.top - height - 4 : r.bottom + 4;
    setMenu({ top: Math.max(8, top), left: Math.max(8, Math.min(r.right - 208, window.innerWidth - 216)) });
  };

  const rename = async () => {
    const next = title.replace(/\s+/g, ' ').trim();
    setEditing(false);
    if (!next || next === thread.title) { setTitle(thread.title); return; }
    upsert({ id: thread.id, title: next });
    const r = await clientApi<ChatThreadSummary>(`ask/threads/${thread.id}`, { method: 'PATCH', body: { title: next } });
    if (!r.ok) { upsert({ id: thread.id, title: thread.title }); setTitle(thread.title); toast(t('chat.item.failed')); }
  };
  const togglePin = async () => {
    setMenu(null);
    upsert({ id: thread.id, pinned: !thread.pinned });
    const r = await clientApi<ChatThreadSummary>(`ask/threads/${thread.id}`, { method: 'PATCH', body: { pinned: !thread.pinned } });
    if (!r.ok) { upsert({ id: thread.id, pinned: thread.pinned }); toast(t('chat.item.failed')); return; }
    toast(thread.pinned ? t('chat.item.unsaved') : t('chat.item.saved'));
  };
  const doDelete = async () => {
    setBusy(true);
    const r = await clientApi(`ask/threads/${thread.id}`, { method: 'DELETE' });
    setBusy(false);
    if (!r.ok && r.status !== 404) { toast(t('chat.item.failed')); return; }
    setConfirm(false);
    remove(thread.id);
    toast(t('chat.item.deleted'));
    if (active) { announceNewChat(); router.push(`/${locale}/ask`); }
  };

  return (
    <li className={styles.item} data-active={active || undefined}>
      {editing ? (
        <input className={styles.renameInput} value={title} maxLength={120} autoFocus aria-label={t('chat.item.renameLabel')}
          onChange={(e) => setTitle(e.target.value)} onBlur={() => void rename()}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void rename(); } if (e.key === 'Escape') { setTitle(thread.title); setEditing(false); } }} />
      ) : (
        <Link href={`/${locale}/ask/${thread.id}`} className={styles.itemLink} aria-current={active ? 'page' : undefined} onClick={onNavigate} title={thread.title}>
          {thread.pinned ? <BadgeCheck size={16} aria-hidden="true" className={styles.pinIcon} /> : null}
          <span className={styles.itemTitle}>{thread.title}</span>
        </Link>
      )}
      {!editing ? (
        <button ref={moreRef} type="button" className={styles.itemMore} aria-haspopup="menu" aria-expanded={Boolean(menu)}
          aria-label={t('chat.item.menu', { title: thread.title })} onClick={() => (menu ? setMenu(null) : openMenu())}>
          <Ellipsis size={18} aria-hidden="true" />
        </button>
      ) : null}
      {menu ? (
        <div ref={menuRef} className={styles.menu} role="menu" style={{ top: menu.top, left: menu.left }}>
          <button type="button" role="menuitem" onClick={() => { setMenu(null); setEditing(true); }}><Pencil size={16} aria-hidden="true" /> {t('chat.item.rename')}</button>
          <button type="button" role="menuitem" onClick={() => void togglePin()}><BadgeCheck size={16} aria-hidden="true" /> {thread.pinned ? t('chat.item.unsave') : t('chat.item.save')}</button>
          <button type="button" role="menuitem" data-danger onClick={() => { setMenu(null); setConfirm(true); }}><Trash2 size={16} aria-hidden="true" /> {t('chat.item.delete')}</button>
        </div>
      ) : null}
      <Dialog open={confirm} title={t('chat.item.deleteTitle')} onCancel={() => { if (!busy) setConfirm(false); }}
        actions={<>
          <Button variant="secondary" onClick={() => setConfirm(false)} disabled={busy}>{t('common.cancel')}</Button>
          <Button variant="danger" loading={busy} loadingLabel={t('fields.deleting')} onClick={() => void doDelete()}>{t('chat.item.delete')}</Button>
        </>}>
        <p>{t('chat.item.deleteBody', { title: thread.title })}</p>
      </Dialog>
    </li>
  );
}
