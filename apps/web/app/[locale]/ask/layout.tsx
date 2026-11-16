import { Suspense, type ReactNode } from 'react';
import { AskFrame } from '@/components/Chat/AskFrame';
import { ChatSkeleton } from '@/components/Chat/ChatSkeleton';
import { ChatsProvider } from '@/components/Chat/ChatsProvider';
import { getChatThreads, getFields, getHealth, getMe, redirectIfUnauthenticated } from '@/lib/api';
import type { Locale } from '@/lib/locales';

/**
 * R5 Ask (PRD §7.5). The history and what every conversation needs from the account are loaded once here, so
 * moving between conversations only loads the conversation (docs/UX_QA_AUDIT.md ASK-08).
 */
export default function AskLayout({ children, params }: { children: ReactNode; params: Promise<{ locale: string }> }) {
  return (
    <Suspense fallback={<ChatSkeleton frame />}>
      <AskData params={params}>{children}</AskData>
    </Suspense>
  );
}

async function AskData({ children, params }: { children: ReactNode; params: Promise<{ locale: string }> }) {
  const locale = (await params).locale as Locale;
  const [threads, fields, me, health] = await Promise.all([getChatThreads(), getFields(), getMe(), getHealth()]);
  await redirectIfUnauthenticated(fields, locale);
  // Voice needs a speech-to-text service on the server (Bhashini or local Whisper). Unknown counts as unavailable.
  const voiceAvailable = health.ok && (health.data.integrations?.bhashini === 'configured' || health.data.integrations?.whisper === 'configured');
  return (
    <ChatsProvider initial={threads.ok ? threads.data : { items: [], next_cursor: null }} historyFailed={!threads.ok}
      fields={fields.ok ? fields.data.map((f) => ({ id: f.id, name: f.name, crop: f.crop })) : []}
      kvk={me.ok ? me.data.district_kvk : null} voiceAvailable={voiceAvailable}>
      <AskFrame>{children}</AskFrame>
    </ChatsProvider>
  );
}
