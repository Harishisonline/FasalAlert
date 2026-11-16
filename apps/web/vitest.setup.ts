import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import { createElement, type AnchorHTMLAttributes } from 'react';

// next/link needs the App Router at runtime; a plain anchor is enough for component tests.
vi.mock('next/link', () => ({
  default: ({ href, children, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; prefetch?: boolean; replace?: boolean; scroll?: boolean }) => {
    const anchorProps: Record<string, unknown> = { ...rest };
    delete anchorProps.prefetch;
    delete anchorProps.replace;
    delete anchorProps.scroll;
    return createElement('a', { href, ...anchorProps }, children);
  },
}));

afterEach(() => {
  cleanup();
});
