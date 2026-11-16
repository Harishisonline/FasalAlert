'use client';
import type { ReactNode } from 'react';
import { SerwistProvider } from '@serwist/turbopack/react';

/** Registers the Serwist service worker in production builds (design.md 20.5). */
export function PwaRegister({ children }: { children: ReactNode }) {
  return (
    <SerwistProvider swUrl="/serwist/sw.js" disable={process.env.NODE_ENV !== 'production'} reloadOnOnline={false} cacheOnNavigation>
      {children}
    </SerwistProvider>
  );
}
