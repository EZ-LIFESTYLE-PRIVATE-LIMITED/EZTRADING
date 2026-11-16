// PWA: registers the service worker and offers "Install app" when the browser allows it.
import { $ } from "./ui.js";

const standalone = () =>
  window.matchMedia("(display-mode: standalone)").matches || document.referrer.startsWith("android-app://");

export function initInstall() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => { /* offline support is best-effort */ });
  }
  const btn = $("install-app");
  if (!btn || standalone()) return;  // already running as an app (PWA or Android TWA)
  let deferred = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e;
    btn.classList.remove("hidden");
  });
  window.addEventListener("appinstalled", () => btn.classList.add("hidden"));
  btn.addEventListener("click", async () => {
    $("user-menu").classList.add("hidden");
    if (!deferred) return;
    deferred.prompt();
    await deferred.userChoice.catch(() => {});
    deferred = null;
    btn.classList.add("hidden");
  });
}
