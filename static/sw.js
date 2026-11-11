// Service worker: shows push notifications and focuses the app when clicked.
self.addEventListener("push", (event) => {
  let data = { title: "EZTrading", body: "", url: "/" };
  try { data = { ...data, ...event.data.json() }; } catch (_) { /* plain text */ }
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body,
    data: { url: data.url },
    tag: "eztrading",
    renotify: true,
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
