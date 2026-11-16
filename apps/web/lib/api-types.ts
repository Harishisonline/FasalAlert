import type { ApiError } from '@fasalalert/shared/api';

export type ApiErrorBody = ApiError['error'];

/** Every API call resolves to a result. Expected failures are data, never thrown (PRD §13 rule 2). */
export type ApiResult<T> =
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; kind: 'network' | 'http'; error: ApiErrorBody | null };

export function parseErrorBody(body: unknown): ApiErrorBody | null {
  if (body && typeof body === 'object' && 'error' in body) {
    const e = (body as { error: unknown }).error;
    if (e && typeof e === 'object' && 'code' in e) {
      const err = e as Partial<ApiErrorBody>;
      return {
        code: (err.code ?? 'internal_error') as ApiErrorBody['code'],
        message: String(err.message ?? ''),
        details: (err.details ?? {}) as Record<string, unknown>,
        trace_id: String(err.trace_id ?? ''),
      };
    }
  }
  return null;
}

export function errorCode(r: ApiResult<unknown>): ApiErrorBody['code'] | 'network' | null {
  if (r.ok) return null;
  if (r.kind === 'network') return 'network';
  return r.error?.code ?? null;
}

export function retryAfterSeconds(r: ApiResult<unknown>): number | null {
  if (r.ok || !r.error) return null;
  const v = r.error.details?.retry_after;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export function traceId(r: ApiResult<unknown>): string | null {
  return !r.ok && r.error?.trace_id ? r.error.trace_id : null;
}
