import { NextResponse, type NextRequest } from 'next/server';
import { envelope, sameOrigin } from '@/lib/bff';
import { clearedCookies } from '@/lib/tokens';

/** POST /api/auth/signout: clear the session cookies (the API has no sign-out endpoint in §11). */
export async function POST(req: NextRequest) {
  if (!sameOrigin(req)) return envelope(403, 'forbidden', 'Cross-site request refused');
  const res = new NextResponse(null, { status: 204, headers: { 'cache-control': 'no-store' } });
  for (const c of clearedCookies()) res.cookies.set(c);
  return res;
}
