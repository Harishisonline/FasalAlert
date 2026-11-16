import type { NextRequest } from 'next/server';
import { envelope, passThrough, sameOrigin, upstream } from '@/lib/bff';

/** POST /api/auth/otp/request -> FastAPI POST /auth/otp/request {phone} (PRD §7.2, §11). */
export async function POST(req: NextRequest) {
  if (!sameOrigin(req)) return envelope(403, 'forbidden', 'Cross-site request refused');
  const body = (await req.json().catch(() => null)) as { phone?: unknown } | null;
  const phone = typeof body?.phone === 'string' ? body.phone : '';
  if (!/^\+91[6-9]\d{9}$/.test(phone)) return envelope(400, 'validation_error', 'Enter a 10-digit mobile number.', { field: 'phone' });
  const res = await upstream('auth/otp/request', { method: 'POST', body: JSON.stringify({ phone }) });
  if (!res) return envelope(503, 'internal_error', 'The sign-in service is unreachable.', { reason: 'upstream_unreachable' });
  return passThrough(res);
}
