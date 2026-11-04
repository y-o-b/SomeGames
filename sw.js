// Service Worker: macht die Seite offline nutzbar.
// Strategie: Netzwerk zuerst (mit kurzem Timeout), bei Fehler oder Offline aus dem Cache.
// So sieht man online immer den neuesten Stand, offline den zuletzt geladenen.
const CACHE = 'y-o-b-v25';
const NETWORK_TIMEOUT_MS = 4000;

// Alles, was die Spiele zum Starten brauchen. Neue Dateien hier ergänzen und CACHE erhöhen.
const PRECACHE = [
  './',
  'index.html',
  'tictactoe.html',
  'memory.html',
  'solitaire.html',
  'minesweeper.html',
  'solitaire-deals.json',
  'VERSION',
  'manifest.webmanifest',
  'favicon.svg',
  'favicon.ico',
  'apple-touch-icon.png',
  'icons/pwa-192.png',
  'icons/pwa-512.png',
  'icons/pwa-maskable-512.png',
  'icons/tictactoe.svg',
  'icons/tictactoe.ico',
  'icons/tictactoe-180.png',
  'icons/memory.svg',
  'icons/memory.ico',
  'icons/memory-180.png',
  'icons/solitaire.svg',
  'icons/solitaire.ico',
  'icons/solitaire-180.png',
  'icons/minesweeper.svg',
  'icons/minesweeper-180.png'
];

self.addEventListener('install', event => {
  // cache: 'reload' umgeht den HTTP-Cache, damit wirklich der aktuelle Stand gespeichert wird.
  event.waitUntil(
    caches.open(CACHE)
      .then(cache => Promise.all(PRECACHE.map(url => cache.add(new Request(url, { cache: 'reload' })))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key.startsWith('y-o-b-') && key !== CACHE).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

// Cache-Schlüssel ohne Query-String: Cache-Buster wie VERSION?123 oder ?v=… würden sonst den Cache endlos füllen.
const cacheKey = url => new Request(url.origin + url.pathname);

function networkWithTimeout(request) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), NETWORK_TIMEOUT_MS);
    fetch(request).then(response => { clearTimeout(timer); resolve(response); }, error => { clearTimeout(timer); reject(error); });
  });
}

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const response = await networkWithTimeout(request);
      // Nur vollständige, erfolgreiche Antworten merken.
      if (response.ok && response.status === 200) cache.put(cacheKey(url), response.clone());
      return response;
    } catch (error) {
      // Offline: Query-Strings (z. B. ?v=…, Cache-Buster) werden ignoriert.
      const cached = await cache.match(cacheKey(url));
      if (cached) return cached;
      if (request.mode === 'navigate') return (await cache.match('index.html')) || Response.error();
      return Response.error();
    }
  })());
});
