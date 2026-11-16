/** Server-side base URL of the FastAPI backend. Never sent to the browser. */
export function apiBaseUrl(): string {
  return (process.env.API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/+$/, '');
}

export const ACCESS_COOKIE = 'fa_at';
export const REFRESH_COOKIE = 'fa_rt';
/** Access token lifetime from the backend (PRD §12: 15 minutes). */
export const ACCESS_MAX_AGE_S = 15 * 60;
/** Refresh token lifetime (REFRESH_TOKEN_TTL_DAYS default 30). */
export const REFRESH_MAX_AGE_S = 30 * 24 * 60 * 60;

export const KISAN_CALL_CENTRE = '1800-180-1551';

/** Routes under /[locale] that need a session (PRD §6). */
/* Regional outlook (map) needs an account too: the landing page is the only public page (docs/UX_QA_AUDIT.md LAND-03). */
export const PROTECTED_SEGMENTS = new Set(['home', 'fields', 'field', 'ask', 'alert', 'market', 'map', 'onboarding', 'settings']);
