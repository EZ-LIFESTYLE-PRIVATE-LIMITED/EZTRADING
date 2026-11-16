// Service worker: offline app shell + push notifications.
//
// Caching is network-first for static assets: the server sends Cache-Control: no-cache (no hashed
// filenames), so online users always get fresh, consistent ES modules; the cache is only a fallback
// when the network is down. API, auth and webhook traffic is never intercepted.
const CACHE = "ezt-shell-v1";
const SHELL = [
  "/",
  "/index.html",
  "/login.html",
  "/offline.html",
  "/styles.css",
  "/manifest.webmanifest",
  "/js/theme.js",
  "/js/app.js",
  "/js/api.js",
  "/js/state.js",
  "/js/ui.js",
  "/js/push.js",
  "/js/install.js",
  "/js/login.js",
  "/js/views/portfolio.js",
  "/js/views/plan.js",
  "/js/views/ipo.js",
  "/js/views/settings.js",
  "/icons/icon-192.png",
  "/icons/favicon-32.png",
  "/icons/icon.svg",
];
const NEVER = ["/api/", "/auth/", "/billing/", "/telegram/", "/healthz"];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // One missing file must not block install.
    await Promise.all(SHELL.map((url) => cache.add(new Request(url, { cache: "reload" })).catch(() => {})));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k.startsWith("ezt-") && k !== CACHE).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

function cacheable(request, url) {
  if (request.method !== "GET" || url.origin !== self.location.origin) return false;
  if (NEVER.some((p) => url.pathname.startsWith(p))) return false;
  if (request.mode === "navigate") return true;
  return /\.(?:html|css|js|png|svg|webmanifest)$/.test(url.pathname);
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (!cacheable(request, url)) return;  // let the browser handle it normally
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const response = await fetch(request);
      // Only cache clean same-origin 200s (not redirects to /login.html etc.).
      if (response.ok && response.type === "basic" && !response.redirected) {
        cache.put(request.mode === "navigate" ? url.pathname : request, response.clone());
      }
      return response;
    } catch (err) {
      const hit = await cache.match(request.mode === "navigate" ? url.pathname : request, { ignoreSearch: true });
      if (hit) return hit;
      if (request.mode === "navigate") return (await cache.match("/offline.html")) || Response.error();
      throw err;
    }
  })());
});

self.addEventListener("push", (event) => {
  let data = { title: "EZTrading", body: "", url: "/" };
  try { data = { ...data, ...event.data.json() }; } catch (_) { /* plain text */ }
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body,
    data: { url: data.url },
    tag: "eztrading",
    renotify: true,
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";
  event.waitUntil((async () => {
    const all = await clients.matchAll({ type: "window", includeUncontrolled: true });
    const existing = all.find((c) => new URL(c.url).origin === self.location.origin);
    if (existing) { await existing.focus(); return existing.navigate(url); }
    return clients.openWindow(url);
  })());
});
