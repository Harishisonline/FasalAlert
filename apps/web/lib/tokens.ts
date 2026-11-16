/**
 * Token cookie helpers shared by proxy.ts and the BFF route handlers. Tokens live only in
 * httpOnly cookies and are never exposed to client JavaScript.
 */
import type { RefreshResponse } from '@fasalalert/shared/api';
import { ACCESS_COOKIE, ACCESS_MAX_AGE_S, REFRESH_COOKIE, REFRESH_MAX_AGE_S, apiBaseUrl } from './config';

export interface CookieSpec {
  name: string;
  value: string;
  httpOnly: true;
  secure: boolean;
  sameSite: 'lax';
  path: '/';
  maxAge: number;
}

function secure(): boolean {
  return process.env.NODE_ENV === 'production';
}

/** Expiry (ms since epoch) from a JWT payload, without verifying it. The API verifies. */
export function jwtExpiry(token: string | undefined | null): number | null {
  if (!token) return null;
  const part = token.split('.')[1];
  if (!part) return null;
  try {
    const json = JSON.parse(Buffer.from(part.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8')) as { exp?: number };
    return typeof json.exp === 'number' ? json.exp * 1000 : null;
  } catch {
    return null;
  }
}

/** True when the access token is missing or expires within the margin. */
export function needsRefresh(access: string | undefined | null, marginMs = 60_000, now = Date.now()): boolean {
  if (!access) return true;
  const exp = jwtExpiry(access);
  return exp !== null && exp - now < marginMs;
}

export function tokenCookies(tokens: { access_token: string; refresh_token: string }): CookieSpec[] {
  const exp = jwtExpiry(tokens.access_token);
  const accessAge = exp ? Math.max(30, Math.min(ACCESS_MAX_AGE_S, Math.floor((exp - Date.now()) / 1000))) : ACCESS_MAX_AGE_S;
  return [
    { name: ACCESS_COOKIE, value: tokens.access_token, httpOnly: true, secure: secure(), sameSite: 'lax', path: '/', maxAge: accessAge },
    { name: REFRESH_COOKIE, value: tokens.refresh_token, httpOnly: true, secure: secure(), sameSite: 'lax', path: '/', maxAge: REFRESH_MAX_AGE_S },
  ];
}

export function clearedCookies(): CookieSpec[] {
  return [ACCESS_COOKIE, REFRESH_COOKIE].map((name) => ({
    name, value: '', httpOnly: true, secure: secure(), sameSite: 'lax', path: '/', maxAge: 0,
  }));
}

export type RefreshOutcome =
  | { kind: 'ok'; tokens: RefreshResponse }
  | { kind: 'rejected'; status: number }
  | { kind: 'unreachable' };

type RefreshStore = Map<string, { at: number; promise: Promise<RefreshOutcome> }>;
const g = globalThis as typeof globalThis & { __faRefresh?: RefreshStore };
const inflight: RefreshStore = (g.__faRefresh ??= new Map());

/**
 * Exchange a refresh token. Concurrent calls with the same token share one upstream request so a
 * rotating refresh token is never presented twice by this server process.
 */
export function refreshTokens(refreshToken: string): Promise<RefreshOutcome> {
  const now = Date.now();
  for (const [k, v] of inflight) if (now - v.at > 30_000) inflight.delete(k);
  const existing = inflight.get(refreshToken);
  if (existing) return existing.promise;
  const promise = (async (): Promise<RefreshOutcome> => {
    try {
      const res = await fetch(`${apiBaseUrl()}/auth/refresh`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', accept: 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
        cache: 'no-store',
        signal: AbortSignal.timeout(6000),
      });
      if (!res.ok) return { kind: 'rejected', status: res.status };
      const body = (await res.json()) as RefreshResponse;
      if (!body?.access_token || !body?.refresh_token) return { kind: 'rejected', status: 502 };
      return { kind: 'ok', tokens: body };
    } catch {
      return { kind: 'unreachable' };
    }
  })();
  inflight.set(refreshToken, { at: now, promise });
  return promise;
}
