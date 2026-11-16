'use client';
import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { createTranslator, type Messages, type Translator } from '@/lib/i18n';
import type { Locale } from '@/lib/locales';

interface I18nValue { locale: Locale; t: Translator }
const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({ locale, messages, children }: { locale: Locale; messages: Messages; children: ReactNode }) {
  const value = useMemo(() => ({ locale, t: createTranslator(locale, messages) }), [locale, messages]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const v = useContext(I18nContext);
  if (!v) throw new Error('useI18n outside I18nProvider');
  return v;
}

export function useT(): Translator {
  return useI18n().t;
}
