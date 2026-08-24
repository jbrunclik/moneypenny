/**
 * Service worker: push notifications + offline app shell.
 *
 * Caching strategy (deliberately conservative so it can't serve stale UI):
 * - Navigations (the SPA shell): network-first, cache fallback. Online
 *   users always get the freshest shell; offline users get the last one.
 * - /static/assets/* (content-hashed filenames): cache-first. Immutable by
 *   construction - a new build ships new URLs.
 * - /api/* and everything else: network only, never cached.
 *
 * Push payload shape (see src/utils/push.py): { title, body, url?, tag? }
 */

const SHELL_CACHE = 'shell-v1';
const ASSET_CACHE = 'assets-v1';

self.addEventListener('install', () => {
  // Activate updated workers immediately
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([SHELL_CACHE, ASSET_CACHE]);
      const names = await caches.keys();
      await Promise.all(names.filter((n) => !keep.has(n)).map((n) => caches.delete(n)));
      await self.clients.claim();
    })()
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // API and auth traffic is never cached
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/auth/')) return;

  // App shell: network-first with cache fallback
  if (request.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          const response = await fetch(request);
          if (response.ok) {
            const cache = await caches.open(SHELL_CACHE);
            cache.put('/', response.clone());
          }
          return response;
        } catch {
          const cached = await caches.match('/', { cacheName: SHELL_CACHE });
          if (cached) return cached;
          return new Response(
            '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">' +
              '<title>Offline</title><body style="font-family:system-ui;background:#0f0f0f;color:#eee;' +
              'display:flex;align-items:center;justify-content:center;height:100vh;margin:0">' +
              '<div style="text-align:center"><h1>You\'re offline</h1>' +
              '<p>AI Chatbot needs a connection for the first load.</p></div>',
            { status: 503, headers: { 'Content-Type': 'text/html' } }
          );
        }
      })()
    );
    return;
  }

  // Hashed build assets: cache-first (immutable URLs)
  if (url.pathname.startsWith('/static/assets/') || url.pathname === '/static/manifest.json') {
    event.respondWith(
      (async () => {
        const cached = await caches.match(request, { cacheName: ASSET_CACHE });
        if (cached) return cached;
        const response = await fetch(request);
        if (response.ok) {
          const cache = await caches.open(ASSET_CACHE);
          cache.put(request, response.clone());
        }
        return response;
      })()
    );
  }
});

self.addEventListener('push', (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { title: 'AI Chatbot', body: event.data ? event.data.text() : '' };
  }

  const title = payload.title || 'AI Chatbot';
  const url = payload.url || '/';
  const options = {
    body: payload.body || '',
    icon: '/static/icon-192.png',
    badge: '/static/icon-192.png',
    tag: payload.tag || undefined,
    data: { url },
  };

  event.waitUntil(
    (async () => {
      // Nudge every open app window to sync right away - without this,
      // in-app badges and threads stay stale until the next poll tick
      // even though the push already announced the change
      const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const client of wins) {
        client.postMessage({ type: 'push-received' });
      }

      // Suppress when a focused window is already viewing the target
      // route - the user is looking at the answer right now
      const hashIndex = url.indexOf('#');
      const targetHash = hashIndex >= 0 ? url.slice(hashIndex) : null;
      if (targetHash) {
        const viewingTarget = wins.some((client) => {
          try {
            return client.focused && new URL(client.url).hash === targetHash;
          } catch {
            return false;
          }
        });
        if (viewingTarget) return;
      }
      await self.registration.showNotification(title, options);
    })()
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      // Focus an existing app window and tell the app to handle the
      // route. A hard client.navigate() is wrong here: navigating to an
      // identical hash URL is a no-op (already-open conversation never
      // refreshed), and a reload would drop app state. The app listens
      // for this message (core/push.ts), routes, and syncs new messages.
      for (const client of clients) {
        if ('focus' in client) {
          client.focus();
          client.postMessage({ type: 'push-navigate', url });
          return undefined;
        }
      }
      return self.clients.openWindow(url);
    })
  );
});
