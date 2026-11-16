'use client';
/**
 * Browser-side API calls. Everything goes through the BFF proxy (/api/proxy/...), which attaches
 * the Bearer token from the httpOnly cookie and refreshes it on 401. Tokens never reach this code.
 */
import { parseErrorBody, type ApiResult } from './api-types';

export async function clientApi<T>(
  path: string,
  init: { method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'; body?: unknown; query?: Record<string, string | number | undefined | null>; signal?: AbortSignal } = {},
): Promise<ApiResult<T>> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(init.query ?? {})) if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
  const url = `/api/proxy/${path.replace(/^\/+/, '')}${qs.size ? `?${qs.toString()}` : ''}`;
  try {
    const res = await fetch(url, {
      method: init.method ?? 'GET',
      headers: init.body === undefined ? { accept: 'application/json' } : { accept: 'application/json', 'content-type': 'application/json' },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      credentials: 'same-origin',
      signal: init.signal,
    });
    const text = await res.text();
    let json: unknown = null;
    if (text) {
      try { json = JSON.parse(text); } catch { json = null; }
    }
    if (!res.ok) return { ok: false, status: res.status, kind: 'http', error: parseErrorBody(json) };
    return { ok: true, status: res.status, data: json as T };
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    return { ok: false, status: 0, kind: 'network', error: null };
  }
}

/** Send the user to R2 with ?next= after a definitive 401 (design.md 20.3). */
export function goToSignIn(locale: string): void {
  const next = `${window.location.pathname}${window.location.search}`;
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- a full load after the session ends
  window.location.assign(`/${locale}/signin?next=${encodeURIComponent(next)}&reason=expired`);
}
