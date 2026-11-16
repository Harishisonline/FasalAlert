/// <reference lib="esnext" />
/// <reference lib="webworker" />
/**
 * Serwist service worker (design.md 20.5), bundled by app/serwist/[path]/route.ts per Serwist's
 * Turbopack guide. Strategies follow the table in 20.5: decisions and fields NetworkFirst with a 4 s
 * timeout; auth network only; settings PATCHes never queued; read and feedback POSTs queued.
 */
import { defaultCache } from '@serwist/turbopack/worker';
import type { PrecacheEntry, RuntimeCaching, SerwistGlobalConfig, SerwistPlugin } from 'serwist';
import { BackgroundSyncPlugin, CacheFirst, ExpirationPlugin, NetworkFirst, NetworkOnly, Serwist } from 'serwist';

declare global {
  interface WorkerGlobalScope extends SerwistGlobalConfig {
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined;
  }
}
declare const self: ServiceWorkerGlobalScope;

/** Treat upstream 5xx as a network failure so NetworkFirst falls back to the cached copy. */
const failOn5xx: SerwistPlugin = {
  fetchDidSucceed: async ({ response }) => {
    if (response.status >= 500) throw new Error(`upstream ${response.status}`);
    return response;
  },
};

const api = (re: RegExp) => ({ url, request }: { url: URL; request: Request }) => url.origin === self.location.origin && request.method === 'GET' && re.test(url.pathname);

const runtimeCaching: RuntimeCaching[] = [
  { matcher: ({ url }) => url.pathname.startsWith('/api/auth/'), handler: new NetworkOnly() },
  {
    matcher: api(/^\/api\/proxy\/(decisions\/today|fields(\/\d+)?)$/),
    handler: new NetworkFirst({ cacheName: 'fa-api-core', networkTimeoutSeconds: 4, plugins: [failOn5xx] }),
  },
  { matcher: api(/^\/api\/proxy\/(alerts|users\/me)$/), handler: new NetworkFirst({ cacheName: 'fa-api-user', networkTimeoutSeconds: 4, plugins: [failOn5xx] }) },
  { matcher: api(/^\/api\/proxy\/public\//), handler: new NetworkFirst({ cacheName: 'fa-api-public', networkTimeoutSeconds: 4, plugins: [failOn5xx] }) },
  {
    matcher: api(/^\/api\/proxy\/(market|transport|weather|risks|locations)\//),
    handler: new NetworkFirst({ cacheName: 'fa-api-data', networkTimeoutSeconds: 6, plugins: [failOn5xx, new ExpirationPlugin({ maxAgeSeconds: 24 * 3600, maxEntries: 200 })] }),
  },
  {
    matcher: ({ url, request }) => request.method === 'POST' && /^\/api\/proxy\/alerts\/\d+\/(read|feedback)$/.test(url.pathname),
    handler: new NetworkOnly({ plugins: [new BackgroundSyncPlugin('fa-alert-actions', { maxRetentionTime: 24 * 60 })] }),
    method: 'POST',
  },
  { matcher: ({ url }) => url.pathname.startsWith('/api/'), handler: new NetworkOnly() },
  { matcher: ({ url }) => url.pathname.startsWith('/geo/') || url.pathname.startsWith('/maplibre/'), handler: new CacheFirst({ cacheName: 'fa-static-data' }) },
  ...defaultCache,
];

const offlineFor = (l: string) => ({
  url: `/${l}/offline`,
  matcher: ({ request }: { request: Request }) => {
    const path = new URL(request.url).pathname;
    return request.destination === 'document' && (path === `/${l}` || path.startsWith(`/${l}/`));
  },
});

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching,
  fallbacks: {
    entries: [
      offlineFor('en'),
      offlineFor('hi'),
      offlineFor('mr'),
      { url: '/mr/offline', matcher: ({ request }: { request: Request }) => request.destination === 'document' },
    ],
  },
});

serwist.addEventListeners();

/* Web Push (design.md 12.6). The payload format is set by the backend: JSON {title, body, url} or text. */
self.addEventListener('push', (event) => {
  let data: { title?: string; body?: string; url?: string } = {};
  try {
    data = event.data?.json() ?? {};
  } catch {
    data = { body: event.data?.text() };
  }
  const url = typeof data.url === 'string' && data.url.startsWith('/') && !data.url.startsWith('//') ? data.url : '/';
  event.waitUntil(self.registration.showNotification(data.title || 'FasalAlert', {
    body: data.body ?? '',
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    data: { url },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data as { url?: string } | null)?.url ?? '/';
  event.waitUntil(self.clients.openWindow(url));
});
