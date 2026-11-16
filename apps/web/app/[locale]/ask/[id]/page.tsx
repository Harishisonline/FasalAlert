import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { ChatWorkspace } from '@/components/Chat/ChatWorkspace';
import { RetryButton } from '@/components/Feedback/RetryButton';
import { RouteError } from '@/components/Feedback/RouteError';
import styles from '@/components/Chat/Chat.module.css';
import { getChatThread } from '@/lib/api';
import { createTranslator } from '@/lib/i18n';
import { isLocale, type Locale } from '@/lib/locales';

function threadId(raw: string): number | null {
  return /^\d{1,12}$/.test(raw) ? Number(raw) : null;
}

export async function generateMetadata({ params }: { params: Promise<{ locale: string; id: string }> }): Promise<Metadata> {
  const { locale, id } = await params;
  const t = createTranslator(isLocale(locale) ? locale : 'mr');
  const n = threadId(id);
  const r = n === null ? null : await getChatThread(n);
  return { title: r?.ok ? `${r.data.title} · ${t('ask.title')}` : t('ask.title') };
}

/** A saved conversation (docs/UX_QA_AUDIT.md ASK-08). Another farmer's conversation is a 404, never a 403. */
export default async function AskThreadPage({ params }: { params: Promise<{ locale: string; id: string }> }) {
  const { locale, id } = await params;
  const n = threadId(id);
  if (n === null) notFound();
  const r = await getChatThread(n);
  if (!r.ok) {
    if (r.status === 404) notFound();
    const t = createTranslator(locale as Locale);
    return (
      <div className={styles.thread}>
        <RouteError variant="section" message={t('chat.loadError')} code={r.error?.trace_id}
          codeLabel={r.error?.trace_id ? t('state.errorCode', { code: r.error.trace_id }) : undefined} action={<RetryButton />} />
      </div>
    );
  }
  return <ChatWorkspace key={r.data.id} initial={r.data} />;
}
