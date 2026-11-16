import { fireEvent, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithI18n } from '@/test/utils';

const replace = vi.fn();
let pathname = '/mr/field/12';
let search = 'edit=sowing';
vi.mock('next/navigation', () => ({
  usePathname: () => pathname,
  useSearchParams: () => new URLSearchParams(search),
  useRouter: () => ({ replace, push: vi.fn(), refresh: vi.fn() }),
}));

describe('LanguageSwitcher', async () => {
  const { LanguageSwitcher, swapLocale } = await import('./LanguageSwitcher');
  beforeEach(() => { replace.mockReset(); pathname = '/mr/field/12'; search = 'edit=sowing'; });

  it('shows three native-name chips with lang and hreflang, current marked', () => {
    renderWithI18n(<LanguageSwitcher />, 'mr');
    const nav = screen.getByRole('navigation');
    const links = nav.querySelectorAll('a');
    expect([...links].map((a) => a.textContent)).toEqual(['EN', 'मराठी', 'हिंदी']);
    expect([...links].map((a) => a.getAttribute('lang'))).toEqual(['en', 'mr', 'hi']);
    expect([...links].map((a) => a.getAttribute('hreflang'))).toEqual(['en', 'mr', 'hi']);
    expect(links[1]!.getAttribute('aria-current')).toBe('true');
    expect(links[0]!.getAttribute('aria-label')).toBe('EN, English');
  });
  it('swaps the locale segment and keeps the path and query', () => {
    renderWithI18n(<LanguageSwitcher />, 'mr');
    const hi = screen.getByText('हिंदी');
    expect(hi.getAttribute('href')).toBe('/hi/field/12?edit=sowing');
    expect(swapLocale('/en', 'mr')).toBe('/mr');
  });
  it('uses ?lang= on R1', () => {
    pathname = '/';
    search = 'district=NSK';
    renderWithI18n(<LanguageSwitcher mode="query" />, 'en');
    expect(screen.getByText('मराठी').getAttribute('href')).toBe('/?district=NSK&lang=mr');
  });
  it('sets the NEXT_LOCALE cookie on click', () => {
    renderWithI18n(<LanguageSwitcher />, 'mr');
    fireEvent.click(screen.getByText('EN'));
    expect(document.cookie).toContain('NEXT_LOCALE=en');
  });
});
