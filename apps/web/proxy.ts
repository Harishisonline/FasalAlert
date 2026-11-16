/**
 * Next.js 16 proxy (formerly middleware):
 * 1. Resolves the locale for every request (path segment, or ?lang=, NEXT_LOCALE cookie and
 *    Accept-Language on R1) and forwards it, with the path, to Server Components.
 * 2. Refreshes the 15-minute access token from the rotating refresh token before rendering, so
 *    Server Components always see a valid token (they cannot set cookies themselves).
 * 3. Redirects unauthenticated requests for protected routes to /[locale]/signin?next=.
 * 4. Routes entry points (docs/UX_QA_AUDIT.md FLOW-01): `/` is the landing page; a bare `/[locale]` goes to
 *    Home when signed in and to the landing page otherwise; the old `/?district=` map links go to /[locale]/map;
 *    the installed app (`/?source=pwa`) opens on Home when signed in.
 */
import { NextResponse, type NextRequest } from 'next/server';
import { ACCESS_COOKIE, PROTECTED_SEGMENTS, REFRESH_COOKIE } from '@/lib/config';
import { DEFAULT_LOCALE, LOCALE_COOKIE, isLocale, matchAcceptLanguage, type Locale } from '@/lib/locales';
import { needsRefresh, refreshTokens, tokenCookies } from '@/lib/tokens';

function resolveLocale(req: NextRequest, first: string | undefined): Locale {
  if (isLocale(first)) return first;
  const lang = req.nextUrl.searchParams.get('lang');
  if (req.nextUrl.pathname === '/' && isLocale(lang)) return lang;
  const cookie = req.cookies.get(LOCALE_COOKIE)?.value;
  if (isLocale(cookie)) return cookie;
  return matchAcceptLanguage(req.headers.get('accept-language')) ?? DEFAULT_LOCALE;
}

export async function proxy(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const segments = pathname.split('/');
  const first = segments[1] || undefined;
  const second = segments[2];
  const locale = resolveLocale(req, first);
  const isPrefetch = req.headers.get('next-router-prefetch') === '1' || req.headers.get('purpose') === 'prefetch';

  // The regional map moved from `/` to /[locale]/map: keep old shared links working.
  if (pathname === '/' && req.nextUrl.searchParams.has('district')) {
    const url = req.nextUrl.clone();
    url.pathname = `/${locale}/map`;
    url.searchParams.delete('lang');
    return NextResponse.redirect(url);
  }

  const requestHeaders = new Headers(req.headers);
  requestHeaders.set('x-fa-locale', locale);
  requestHeaders.set('x-fa-pathname', `${pathname}${search}`);

  const access = req.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = req.cookies.get(REFRESH_COOKIE)?.value;
  const isLocaleRoute = isLocale(first);
  const isProtected = isLocaleRoute && PROTECTED_SEGMENTS.has(second ?? '');
  let newCookies: ReturnType<typeof tokenCookies> | null = null;
  let authenticated = Boolean(access) && !needsRefresh(access, 0);

  if (refresh && needsRefresh(access) && !isPrefetch) {
    const outcome = await refreshTokens(refresh);
    if (outcome.kind === 'ok') {
      newCookies = tokenCookies(outcome.tokens);
      authenticated = true;
      // Let Server Components in this same request see the new access token.
      const jar = req.cookies.getAll().filter((c) => c.name !== ACCESS_COOKIE && c.name !== REFRESH_COOKIE);
      jar.push({ name: ACCESS_COOKIE, value: outcome.tokens.access_token }, { name: REFRESH_COOKIE, value: outcome.tokens.refresh_token });
      requestHeaders.set('cookie', jar.map((c) => `${c.name}=${encodeURIComponent(c.value)}`).join('; '));
    } else if (outcome.kind === 'unreachable') {
      // The API is down: keep the session and let the page render its honest unavailable state.
      authenticated = authenticated || Boolean(refresh);
    }
    // 'rejected': the session is over. Cookies are not cleared here, because a parallel request may
    // have just rotated them; R2 overwrites them on the next sign in.
  }

  const bareLocale = isLocaleRoute && (second === undefined || second === '');
  const pwaStart = pathname === '/' && req.nextUrl.searchParams.get('source') === 'pwa';
  if (bareLocale || pwaStart) {
    const url = req.nextUrl.clone();
    url.search = '';
    if (authenticated || (pwaStart && refresh)) url.pathname = `/${locale}/home`;
    else { url.pathname = '/'; url.searchParams.set('lang', locale); }
    if (url.pathname !== pathname || bareLocale) {
      const res = NextResponse.redirect(url);
      for (const c of newCookies ?? []) res.cookies.set(c);
      return res;
    }
  }

  if (isProtected && !authenticated) {
    const url = req.nextUrl.clone();
    url.pathname = `/${locale}/signin`;
    url.search = `?next=${encodeURIComponent(`${pathname}${search}`)}`;
    return NextResponse.redirect(url);
  }

  const res = NextResponse.next({ request: { headers: requestHeaders } });
  for (const c of newCookies ?? []) res.cookies.set(c);
  // Remember the language for R1 (?lang=) and for the localised root 404 (design.md 10.1).
  const current = req.cookies.get(LOCALE_COOKIE)?.value;
  const chosen = isLocaleRoute ? locale : pathname === '/' && isLocale(req.nextUrl.searchParams.get('lang')) ? locale : null;
  if (chosen && chosen !== current) res.cookies.set({ name: LOCALE_COOKIE, value: chosen, path: '/', maxAge: 31_536_000, sameSite: 'lax' });
  return res;
}

export const config = {
  matcher: ['/((?!api/|serwist/|_next/static|_next/image|icons/|geo/|maplibre/|licenses/|favicon.ico|manifest.webmanifest|robots.txt).*)'],
};
