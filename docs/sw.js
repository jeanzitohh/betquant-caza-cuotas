const CACHE_NAME = 'caza-cuotas-v4';
const SHELL_URLS = ['./', './index.html', './manifest.webmanifest', './icon-192.png', './icon-512.png'];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(SHELL_URLS).catch(() => {})));
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = event.request.url;
  if (!url.startsWith(self.location.origin)) return;
  event.respondWith(
    fetch(event.request)
      .then(resp => {
        if (resp && resp.status === 200) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(c => c.put(event.request, clone));
        }
        return resp;
      })
      .catch(() => caches.match(event.request))
  );
});

self.addEventListener('push', event => {
  let payload = { title: 'Caza Cuotas', body: 'Nuevo pronóstico o resultado disponible en el Canal.', url: './#canal' };
  try {
    if (event.data) payload = { ...payload, ...event.data.json() };
  } catch (e) {}
  event.waitUntil(
    self.registration.showNotification(payload.title || 'Caza Cuotas', {
      body: payload.body || '',
      icon: './icon-192.png',
      badge: './icon-192.png',
      tag: 'caza-cuotas-alert',
      renotify: true,
      data: { url: payload.url || './#canal' }
    })
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || './#canal';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const client of list) {
        if ('focus' in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(targetUrl);
    })
  );
});
