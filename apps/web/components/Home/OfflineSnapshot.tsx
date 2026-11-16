'use client';
import { useEffect } from 'react';
import { saveSnapshot, type LastKnownSnapshot } from '@/lib/offline';

/** Keeps the last known decisions on this phone for R10 (PRD AC 22, design.md 20.5). */
export function OfflineSnapshot({ snapshot }: { snapshot: LastKnownSnapshot }) {
  useEffect(() => {
    if (navigator.onLine && snapshot.decisions.length) saveSnapshot(snapshot);
  }, [snapshot]);
  return null;
}
