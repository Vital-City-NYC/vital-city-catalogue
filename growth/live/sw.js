// Vital City Live — service worker.
// Shell: cache-first (installable, opens instantly, works offline).
// Data:  network-first with cache fallback, so a dead network still shows the
//        last snapshot and the app says how old it is. Encrypted blobs only —
//        nothing readable is ever stored by the worker itself.
const VERSION = "vc-live-v2";
const SHELL = ["./", "./index.html", "./manifest.webmanifest",
               "./icons/icon-192.png", "./icons/icon-512.png", "./icons/icon-180.png",
               "../fonts/GascogneTS-Light.ttf"];
self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  const isData = /live\.enc$|data\.enc$/.test(u.pathname);
  if (isData) {
    e.respondWith(fetch(e.request).then(r => { const c = r.clone(); caches.open(VERSION).then(x => x.put(e.request, c)); return r; })
      .catch(() => caches.match(e.request)));
    return;
  }
  if (e.request.method !== "GET") return;
  // The app shell itself is network-first: an update must reach installed
  // users on their next open, with the cache only as the offline fallback.
  const isShell = e.request.mode === "navigate" || /\/(index\.html)?$/.test(u.pathname);
  if (isShell && u.origin === location.origin) {
    e.respondWith(fetch(e.request).then(r => { const c = r.clone(); caches.open(VERSION).then(x => x.put(e.request, c)); return r; })
      .catch(() => caches.match(e.request).then(h => h || caches.match("./index.html"))));
    return;
  }
  e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request).then(r => {
    if (u.origin === location.origin || /typekit|fonts/.test(u.host)) { const c = r.clone(); caches.open(VERSION).then(x => x.put(e.request, c)); }
    return r;
  })));
});
