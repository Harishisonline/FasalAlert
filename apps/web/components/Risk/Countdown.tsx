'use client';
import { useEffect, useState } from 'react';
import { useT } from '@/components/I18n';
import { countdownText } from '@/lib/view';

/** Act-by countdown, updated once a minute, not a live region (design.md 14.1). */
export function Countdown({ target, initialNow, className }: { target: string; initialNow: string; className?: string }) {
  const t = useT();
  const [now, setNow] = useState(() => new Date(initialNow));
  useEffect(() => {
    const first = setTimeout(() => setNow(new Date()), 0);
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => { clearTimeout(first); clearInterval(id); };
  }, []);
  const text = countdownText(t, target, now);
  if (!text) return null;
  const urgent = new Date(target).getTime() - now.getTime() < 3 * 3600_000;
  return <span className={className} data-urgent={urgent || undefined}>{text}</span>;
}
