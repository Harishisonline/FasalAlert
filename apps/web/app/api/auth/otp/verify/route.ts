import { NextResponse, type NextRequest } from 'next/server';
import type { OtpVerifyResponse } from '@fasalalert/shared/api';
import { envelope, passThrough, sameOrigin, upstream } from '@/lib/bff';
import { tokenCookies } from '@/lib/tokens';

/**
 * POST /api/auth/otp/verify -> FastAPI POST /auth/otp/verify. On success the tokens go into httpOnly
 * cookies and only the user and routing flags reach the browser.
 */
export async function POST(req: NextRequest) {
  if (!sameOrigin(req)) return envelope(403, 'forbidden', 'Cross-site request refused');
  const body = (await req.json().catch(() => null)) as { phone?: unknown; code?: unknown } | null;
  const phone = typeof body?.phone === 'string' ? body.phone : '';
  const code = typeof body?.code === 'string' ? body.code : '';
  if (!/^\+91[6-9]\d{9}$/.test(phone)) return envelope(400, 'validation_error', 'Invalid phone', { field: 'phone' });
  if (!/^\d{6}$/.test(code)) return envelope(400, 'validation_error', 'Enter the 6-digit code', { field: 'code' });
  const res = await upstream('auth/otp/verify', { method: 'POST', body: JSON.stringify({ phone, code }) });
  if (!res) return envelope(503, 'internal_error', 'The sign-in service is unreachable.', { reason: 'upstream_unreachable' });
  if (!res.ok) return passThrough(res);
  const data = (await res.json().catch(() => null)) as OtpVerifyResponse | null;
  if (!data?.access_token || !data.refresh_token) return envelope(502, 'internal_error', 'Unexpected sign-in response');
  const out = NextResponse.json(
    { user: data.user, is_new_user: Boolean(data.is_new_user), has_fields: data.has_fields !== false },
    { headers: { 'cache-control': 'no-store' } },
  );
  for (const c of tokenCookies(data)) out.cookies.set(c);
  return out;
}
