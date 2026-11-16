'use client';
/** Browser state as external stores (useSyncExternalStore), so server and first client render agree. */
import { useEffect, useRef, useSyncExternalStore } from 'react';

const noop = () => () => {};

export function useOnline(): boolean {
  return useSyncExternalStore(
    (cb) => {
      window.addEventListener('online', cb);
      window.addEventListener('offline', cb);
      return () => { window.removeEventListener('online', cb); window.removeEventListener('offline', cb); };
    },
    () => navigator.onLine,
    () => true,
  );
}

export function useMediaQuery(query: string, serverValue = false): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(query);
      mq.addEventListener('change', cb);
      return () => mq.removeEventListener('change', cb);
    },
    () => window.matchMedia(query).matches,
    () => serverValue,
  );
}

const storageListeners = new Set<() => void>();
export function notifyStorage(): void { storageListeners.forEach((l) => l()); }

/** The raw localStorage string for a key (null on the server, when missing, or when storage is blocked). */
export function useLocalStorage(key: string): string | null {
  return useSyncExternalStore(
    (cb) => {
      storageListeners.add(cb);
      window.addEventListener('storage', cb);
      return () => { storageListeners.delete(cb); window.removeEventListener('storage', cb); };
    },
    () => { try { return localStorage.getItem(key); } catch { return null; } },
    () => null,
  );
}

/** A value computed once in the browser (false or the fallback during server rendering). */
export function useClientValue<T>(get: () => T, server: T): T {
  return useSyncExternalStore(noop, get, () => server);
}

/** Keep a ref pointing at the latest value without writing refs during render. */
export function useLatest<T>(value: T) {
  const ref = useRef(value);
  useEffect(() => { ref.current = value; });
  return ref;
}

/** Timestamps for event handlers and async flows (never called during render). */
export const nowMs = (): number => Date.now();
export const perfNow = (): number => performance.now();
