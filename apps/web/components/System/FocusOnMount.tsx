'use client';
import { useEffect } from 'react';

/** Move focus to a heading when a system page renders (design.md 12.11 to 12.13). */
export function FocusOnMount({ targetId, title }: { targetId: string; title?: string }) {
  useEffect(() => {
    document.getElementById(targetId)?.focus();
    if (title) document.title = title;
  }, [targetId, title]);
  return null;
}
