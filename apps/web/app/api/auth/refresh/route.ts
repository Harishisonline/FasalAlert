import { NextResponse, type NextRequest } from 'next/server';
import { REFRESH_COOKIE } from '@/lib/config';
import { envelope, sameOrigin } from '@/lib/bff';
import { refreshTokens, tokenCookies } from '@/lib/tokens';

/** POST /api/auth/refresh: rotate the session (used after a language change, PRD §7.9). */
export async function POST(req: NextRequest) {
  if (!sameOrigin(req)) return envelope(403, 'forbidden', 'Cross-site request refused');
  const rt = req.cookies.get(REFRESH_COOKIE)?.value;
  if (!rt) return envelope(401, 'unauthenticated', 'No session');
  const outcome = await refreshTokens(rt);
  if (outcome.kind === 'unreachable') return envelope(503, 'internal_error', 'The sign-in service is unreachable.', { reason: 'upstream_unreachable' });
  if (outcome.kind === 'rejected') return envelope(401, 'unauthenticated', 'Session expired');
  const res = NextResponse.json({ ok: true }, { headers: { 'cache-control': 'no-store' } });
  for (const c of tokenCookies(outcome.tokens)) res.cookies.set(c);
  return res;
}
