import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { vi } from 'vitest';
import { I18nProvider } from '@/components/I18n';
import { ToastProvider } from '@/components/UI/Toast';
import { createTranslator, getMessages } from '@/lib/i18n';
import type { Locale } from '@/lib/locales';
import type { ViewCtx } from '@/lib/view';

export function renderWithI18n(ui: ReactElement, locale: Locale = 'en') {
  return render(
    <I18nProvider locale={locale} messages={getMessages(locale)}>
      <ToastProvider>{ui}</ToastProvider>
    </I18nProvider>,
  );
}

export function ctx(locale: Locale = 'en', now = new Date('2026-01-17T16:20:00+05:30')): ViewCtx {
  return { t: createTranslator(locale), locale, now, unit: 'celsius' };
}

export function mockNextNavigation(pathname = '/en/home', search = '') {
  const replace = vi.fn();
  const push = vi.fn();
  const refresh = vi.fn();
  vi.doMock('next/navigation', () => ({
    usePathname: () => pathname,
    useSearchParams: () => new URLSearchParams(search),
    useRouter: () => ({ replace, push, refresh, back: vi.fn(), prefetch: vi.fn() }),
  }));
  return { replace, push, refresh };
}
