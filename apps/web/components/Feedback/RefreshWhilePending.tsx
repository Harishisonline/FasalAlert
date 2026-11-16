'use client';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

/**
 * Re-renders the page every few seconds while something is still being worked out on the server (a new
 * field's first decision), then stops. It renders nothing; the page says what is pending.
 */
export function RefreshWhilePending({ everyMs = 8000, maxTries = 10 }: { everyMs?: number; maxTries?: number }) {
  const router = useRouter();
  useEffect(() => {
    let tries = 0;
    const iv = setInterval(() => {
      tries += 1;
      if (tries > maxTries || document.hidden) { if (tries > maxTries) clearInterval(iv); return; }
      router.refresh();
    }, everyMs);
    return () => clearInterval(iv);
  }, [router, everyMs, maxTries]);
  return null;
}
