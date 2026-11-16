import type { Metadata } from 'next';
import { ChatWorkspace } from '@/components/Chat/ChatWorkspace';
import { createTranslator } from '@/lib/i18n';
import { isLocale } from '@/lib/locales';

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  return { title: createTranslator(isLocale(locale) ? locale : 'mr')('ask.title') };
}

/** A new conversation. The field scope is pre-set from ?field_id= (PRD §7.4). */
export default async function AskPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const fieldId = typeof sp.field_id === 'string' && /^\d+$/.test(sp.field_id) ? Number(sp.field_id) : null;
  return <ChatWorkspace key={`new-${fieldId ?? ''}`} initial={null} initialFieldId={fieldId} />;
}
