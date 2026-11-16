import type { NextRequest } from 'next/server';
import { ACCESS_COOKIE, REFRESH_COOKIE } from '@/lib/config';
import { envelope, passThrough, sameOrigin, upstream } from '@/lib/bff';
import { needsRefresh, refreshTokens, tokenCookies } from '@/lib/tokens';

const SEGMENT = /^[A-Za-z0-9_.~-]+$/;
const MAX_BODY = 2_000_000; // 30 s of mono audio as base64 fits comfortably

/**
 * Catch-all BFF proxy: /api/proxy/<path> -> FastAPI /api/v1/<path> with `Authorization: Bearer`
 * from the httpOnly cookie. Refreshes transparently on 401 and retries once. Auth endpoints are not
 * reachable through it (they have their own handlers).
 */
async function handle(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  if (!path.length || path.some((s) => !SEGMENT.test(s) || s === '.' || s === '..') || path[0] === 'auth') {
    return envelope(404, 'not_found', 'Not found');
  }
  if (req.method !== 'GET' && !sameOrigin(req)) return envelope(403, 'forbidden', 'Cross-site request refused');
  const target = path.map(encodeURIComponent).join('/');
  let body: string | undefined;
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    body = await req.text();
    if (body.length > MAX_BODY) return envelope(413, 'validation_error', 'Request too large', { field: 'body' });
    if (body === '') body = undefined;
  }
  const search = req.nextUrl.search;
  let access = req.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = req.cookies.get(REFRESH_COOKIE)?.value;
  let rotated: ReturnType<typeof tokenCookies> | null = null;

  const tryRefresh = async (): Promise<boolean> => {
    if (!refresh) return false;
    const outcome = await refreshTokens(refresh);
    if (outcome.kind !== 'ok') return false;
    access = outcome.tokens.access_token;
    rotated = tokenCookies(outcome.tokens);
    return true;
  };

  if (refresh && needsRefresh(access)) await tryRefresh();
  let res = await upstream(target, { method: req.method, body, token: access, search, signal: req.signal });
  if (res && res.status === 401 && !rotated && (await tryRefresh())) {
    res = await upstream(target, { method: req.method, body, token: access, search, signal: req.signal });
  }
  if (!res) return envelope(503, 'internal_error', 'The FasalAlert service is unreachable.', { reason: 'upstream_unreachable' });
  const out = await passThrough(res);
  for (const c of (rotated ?? []) as ReturnType<typeof tokenCookies>) out.cookies.set(c);
  return out;
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const PUT = handle;
export const DELETE = handle;
