/* Vital City toolkit - offline worker for the installed app.
   Scope: the whole toolkit. The contacts tool (network/) and VC Live
   (growth/live/) keep their own workers, which take precedence on their pages.

   Network first, always: a fresh nightly build and the latest pages are never
   hidden behind an old copy. Only when the device is offline does it fall back
   to the last copy it saved. The encrypted data files can be kept for offline
   reading; they are useless without the passphrase, which is never stored here.
   Cross-origin requests (fonts, the edit sheet, Slack, Google) pass straight
   through. */
const VERSION = "vc-toolkit-v1";
const SHELL = ["./", "./index.html", "./toolkit.css", "./toolkit.js", "./manifest.webmanifest",
               "./app/icon-192.png", "./app/icon-512.png", "./app/apple-touch-icon.png"];

self.addEventListener("install", e => {
  self.skipWaiting();
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL).catch(() => {})));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.startsWith("vc-toolkit-") && k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  e.respondWith(
    fetch(req).then(res => {
      if (res.ok && res.type === "basic") {
        const copy = res.clone();
        caches.open(VERSION).then(c => c.put(req, copy)).catch(() => {});
      }
      return res;
    }).catch(() => caches.match(req, { ignoreSearch: true }).then(hit => hit ||
      (req.mode === "navigate"
        ? new Response("<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>" +
            "<body style='font-family:system-ui;padding:40px 20px;background:#f7f7f4;color:#050507'>" +
            "<b style='letter-spacing:.2em;font-size:12px'>VITAL CITY</b><h1 style='font-size:22px'>You're offline</h1>" +
            "<p>This page hasn't been opened on this device yet, so there's no saved copy. Pages you've opened before work offline with their last data.</p>",
            { headers: { "Content-Type": "text/html; charset=utf-8" } })
        : Response.error())))
  );
});
