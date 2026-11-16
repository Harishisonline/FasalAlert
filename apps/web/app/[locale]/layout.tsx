import { notFound } from 'next/navigation';
import type { ReactNode } from 'react';
import { I18nProvider } from '@/components/I18n';
import { AppShell } from '@/components/Nav/AppShell';
import { ToastProvider } from '@/components/UI/Toast';
import { getMessages } from '@/lib/i18n';
import { isLocale } from '@/lib/locales';
import { loadShellData } from '@/lib/shell';

/** Locale provider and the AppShell choice for R2 to R12 (design.md 22). */
export default async function LocaleLayout({ children, params }: { children: ReactNode; params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const data = await loadShellData(locale);
  return (
    <I18nProvider locale={locale} messages={getMessages(locale)}>
      <ToastProvider>
        <AppShell data={data}>{children}</AppShell>
      </ToastProvider>
    </I18nProvider>
  );
}
