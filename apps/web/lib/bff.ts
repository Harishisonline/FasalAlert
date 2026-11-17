/** Helpers for the BFF route handlers under app/api (never imported by client code). */
import { NextResponse, type NextRequest } from 'next/server';
import { apiBaseUrl } from './config';

export function envelope(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
  return NextResponse.json({ error: { code, message, details, trace_id: '' } }, { status, headers: { 'cache-control': 'no-store' } });
}

/** State-changing requests must come from this origin (SameSite=Lax cookies plus an Origin check). */
export function sameOrigin(req: NextRequest): boolean {
  const origin = req.headers.get('origin');
  if (!origin) return true; // same-origin fetches from older browsers may omit it; cookies are SameSite=Lax
  try {
    const o = new URL(origin);
    const host = req.headers.get('x-forwarded-host') ?? req.headers.get('host');
    return o.host === host;
  } catch {
    return false;
  }
}

/** Upstream time budget per path.
 *
 * 'ask' runs the full RAG pipeline and 'public/risks' may recompute the district board when the
 * stored one is stale, so both get a long budget. Everything else is a cheap lookup.
 */
export const UPSTREAM_TIMEOUT_MS: Record<string, number> = { ask: 45_000, 'public/risks': 45_000 };
const DEFAULT_UPSTREAM_TIMEOUT_MS = 10_000;

export async function upstream(path: string, init: { method: string; body?: string; token?: string; search?: string; contentType?: string; signal?: AbortSignal }): Promise<Response | null> {
  const headers: Record<string, string> = { accept: 'application/json' };
  if (init.body !== undefined) headers['content-type'] = init.contentType ?? 'application/json';
  if (init.token) headers.authorization = `Bearer ${init.token}`;
  const budget = UPSTREAM_TIMEOUT_MS[path] ?? DEFAULT_UPSTREAM_TIMEOUT_MS;
  try {
    return await fetch(`${apiBaseUrl()}/${path}${init.search ?? ''}`, {
      method: init.method,
      headers,
      body: init.body,
      cache: 'no-store',
      // The browser's own abort (Stop) ends the upstream request too, not only the time limit.
      signal: init.signal ? AbortSignal.any([AbortSignal.timeout(budget), init.signal]) : AbortSignal.timeout(budget),
    });
  } catch {
    return null;
  }
}

/** Pass an upstream JSON response through, dropping any upstream cookies. */
export async function passThrough(res: Response): Promise<NextResponse> {
  const buf = await res.arrayBuffer();
  return new NextResponse(buf.byteLength ? buf : null, {
    status: res.status,
    headers: { 'content-type': res.headers.get('content-type') ?? 'application/json', 'cache-control': 'private, no-store' },
  });
}
