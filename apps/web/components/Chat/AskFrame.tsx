'use client';
import { usePathname } from 'next/navigation';
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import { useI18n } from '@/components/I18n';
import { Sheet } from '@/components/UI/Sheet';
import { ChatHistory } from './ChatHistory';
import styles from './Chat.module.css';

const HistorySheet = createContext<{ open: () => void }>({ open: () => undefined });

/** Opens the conversation history on phones, where it lives in a sheet instead of a side column. */
export function useHistorySheet() {
  return useContext(HistorySheet);
}

/**
 * The Ask frame (docs/UX_QA_AUDIT.md ASK-08): history on the left from 1024 px, the conversation beside it.
 * On smaller screens the history opens as a full-height sheet from the conversation header.
 */
export function AskFrame({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const pathname = usePathname();
  const match = /\/ask\/(\d+)(?:$|[/?#])/.exec(pathname ?? '');
  const activeId = match ? Number(match[1]) : null;
  const [open, setOpen] = useState(false);
  const value = useMemo(() => ({ open: () => setOpen(true) }), []);
  return (
    <HistorySheet.Provider value={value}>
      <div className={styles.frame}>
        <nav className={styles.side} aria-label={t('chat.history')}>
          <ChatHistory activeId={activeId} />
        </nav>
        <main id="main" tabIndex={-1} className={styles.main}>{children}</main>
      </div>
      <Sheet open={open} onClose={() => setOpen(false)} title={t('chat.history')} initial="full"
        expandLabel={t('nav.expand')} collapseLabel={t('nav.collapse')} closeLabel={t('nav.close')}>
        {open ? <ChatHistory activeId={activeId} onNavigate={() => setOpen(false)} /> : null}
      </Sheet>
    </HistorySheet.Provider>
  );
}
