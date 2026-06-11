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
  const options = {
    body: payload.body || '',
    icon: '/static/icon-192.png',
    badge: '/static/icon-192.png',
    tag: payload.tag || undefined,
    data: { url: payload.url || '/' },
  };

  event.waitUntil(self.registration.showNotification(title, options));
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
