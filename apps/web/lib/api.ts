/**
 * Server-side API client (Server Components and route handlers). Reads the access token from the
 * httpOnly cookie and calls FastAPI with `Authorization: Bearer` (PRD §11, AC 25).
 */
import { cookies, headers } from 'next/headers';
import { redirect } from 'next/navigation';
import { cache } from 'react';
import type {
  ActiveRisksResponse, AlertsResponse, Calibration, ChatThreadDetail, ChatThreadPage, DecisionHistoryItem, DecisionsTodayResponse, Field,
  FieldDetail, ForecastResponse, HealthResponse, LocationItem, Mandi, PriceForecastResponse, PricesResponse, PublicDistrictDetail,
  PublicRisksResponse, TransportRiskResponse, UserMeResponse,
} from '@fasalalert/shared/api';
import { ACCESS_COOKIE, REFRESH_COOKIE, apiBaseUrl } from './config';
import { parseErrorBody, type ApiResult } from './api-types';
import type { Locale } from './locales';

export type { ApiResult } from './api-types';

interface CallOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  auth?: boolean;
  timeoutMs?: number;
  query?: Record<string, string | number | undefined | null>;
}

function buildUrl(path: string, query?: CallOptions['query']): string {
  const url = new URL(`${apiBaseUrl()}/${path.replace(/^\/+/, '')}`);
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
  return url.toString();
}

export async function apiCall<T>(path: string, opts: CallOptions = {}): Promise<ApiResult<T>> {
  const { method = 'GET', body, auth = true, timeoutMs = 8000, query } = opts;
  const h: Record<string, string> = { accept: 'application/json' };
  if (body !== undefined) h['content-type'] = 'application/json';
  if (auth) {
    const token = (await cookies()).get(ACCESS_COOKIE)?.value;
    if (!token) return { ok: false, status: 401, kind: 'http', error: { code: 'unauthenticated', message: '', details: {}, trace_id: '' } };
    h.authorization = `Bearer ${token}`;
  }
  try {
    const res = await fetch(buildUrl(path, query), {
      method,
      headers: h,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
      signal: AbortSignal.timeout(timeoutMs),
    });
    const text = await res.text();
    let json: unknown = null;
    if (text) {
      try { json = JSON.parse(text); } catch { json = null; }
    }
    if (!res.ok) return { ok: false, status: res.status, kind: 'http', error: parseErrorBody(json) };
    return { ok: true, status: res.status, data: json as T };
  } catch {
    return { ok: false, status: 0, kind: 'network', error: null };
  }
}

/** True when the request carries a session cookie (it may still be expired or revoked). */
export async function hasSession(): Promise<boolean> {
  const c = await cookies();
  return Boolean(c.get(ACCESS_COOKIE)?.value || c.get(REFRESH_COOKIE)?.value);
}

/** The request path forwarded by proxy.ts, for ?next= redirects and the root 404. */
export async function requestPath(): Promise<string> {
  return (await headers()).get('x-fa-pathname') ?? '/';
}

/** A 401 from the API sends the user to R2 with ?next= (design.md 20.3). */
export async function redirectIfUnauthenticated(r: ApiResult<unknown>, locale: Locale): Promise<void> {
  if (!r.ok && r.status === 401) {
    const next = await requestPath();
    redirect(`/${locale}/signin?next=${encodeURIComponent(next)}&reason=expired`);
  }
}

/* Request-scoped cached fetchers, shared by the locale layout and pages (React cache). */
export const getMe = cache(() => apiCall<UserMeResponse>('users/me'));
export const getFields = cache(() => apiCall<Field[]>('fields'));
export const getChatThreads = cache(() => apiCall<ChatThreadPage>('ask/threads', { query: { limit: 30 } }));
export const getChatThread = cache((id: number) => apiCall<ChatThreadDetail>(`ask/threads/${id}`));
/* A field's first decision, forecast or route can take tens of seconds (live upstream calls). Pages stream these
   sections, so they get time to finish instead of the 8 s default (docs/UX_QA_AUDIT.md HOME-02). */
export const getDecisionsToday = cache(() => apiCall<DecisionsTodayResponse>('decisions/today', { timeoutMs: 45_000 }));
export const getUnreadAlerts = cache(() => apiCall<AlertsResponse>('alerts', { query: { status: 'unread' } }));
export const getAlerts = cache(() => apiCall<AlertsResponse>('alerts'));
export const getField = cache((id: number) => apiCall<FieldDetail>(`fields/${id}`, { timeoutMs: 30_000 }));
export const getFieldHistory = cache((id: number) => apiCall<DecisionHistoryItem[]>(`fields/${id}/decisions`, { query: { days: 30 } }));
export const getActiveRisks = cache((fieldId: number) => apiCall<ActiveRisksResponse>('risks/active', { query: { field_id: fieldId } }));
export const getForecast = cache((fieldId: number) => apiCall<ForecastResponse>('weather/forecast', { query: { field_id: fieldId, days: 7 }, timeoutMs: 15_000 }));
export const getCalibration = cache((fieldId: number) => apiCall<Calibration>(`fields/${fieldId}/calibration`));
export const getMandis = cache((districtId: number | null, commodity: string, fieldId: number) =>
  apiCall<Mandi[]>('market/mandis', { query: { district_id: districtId ?? undefined, commodity, field_id: fieldId } }));
export const getPrices = cache((commodity: string, market: string, days: number) =>
  apiCall<PricesResponse>('market/prices', { query: { commodity, market, days } }));
export const getPriceForecast = cache((commodity: string, market: string) =>
  apiCall<PriceForecastResponse>('market/forecast', { query: { commodity, market, days: 7 } }));
export const getTransportRisk = cache((fieldId: number) => apiCall<TransportRiskResponse>('transport/risk', { query: { field_id: fieldId, days: 7 }, timeoutMs: 25_000 }));
export const getDistricts = cache(() => apiCall<LocationItem[]>('locations/districts', { auth: false }));
/* Cold public-board compute can exceed the default 8 s; guests still need a useful Regional Outlook. */
export const getPublicRisks = cache(() => apiCall<PublicRisksResponse>('public/risks', { auth: false, timeoutMs: 45_000 }));
export const getPublicDistrict = cache((id: number) => apiCall<PublicDistrictDetail>(`public/districts/${id}`, { auth: false, timeoutMs: 15_000 }));
export const getHealth = cache(() => apiCall<HealthResponse>('health', { auth: false, timeoutMs: 4000 }));
