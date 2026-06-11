/**
 * Push notification service worker.
 *
 * Deliberately minimal: push display + notification click only. No
 * caching/offline logic so it can never break the SPA. Served from
 * /sw.js (Flask route) so its scope covers the whole app.
 *
 * Payload shape (see src/utils/push.py):
 *   { title, body, url?, tag? }
 */

self.addEventListener('install', () => {
  // Activate updated workers immediately; there's no cache to migrate
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
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
      // Suppress when a focused window is already viewing the target
      // route - the user is looking at the answer right now
      const hashIndex = url.indexOf('#');
      const targetHash = hashIndex >= 0 ? url.slice(hashIndex) : null;
      if (targetHash) {
        const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
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
      // Focus an existing app window and navigate it instead of
      // opening a duplicate
      for (const client of clients) {
        if ('focus' in client) {
          client.focus();
          if ('navigate' in client) {
            return client.navigate(url);
          }
          return undefined;
        }
      }
      return self.clients.openWindow(url);
    })
  );
});
