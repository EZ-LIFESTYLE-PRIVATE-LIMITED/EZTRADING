// Web Push for this browser: status, a permission popup, and subscription.
import { api } from "./api.js";
import { $ } from "./ui.js";

function urlBase64ToUint8Array(base64) {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

export const pushSupported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

async function currentSubscription() {
  const reg = await navigator.serviceWorker.getRegistration("/");
  return reg ? reg.pushManager.getSubscription() : null;
}

/** "unsupported" | "blocked" | "on" | "off" for this device. */
export async function pushStatus() {
  if (!pushSupported()) return "unsupported";
  if (Notification.permission === "denied") return "blocked";
  if (Notification.permission === "granted" && (await currentSubscription())) return "on";
  return "off";
}

async function subscribe(publicKey) {
  const reg = await navigator.serviceWorker.register("/sw.js");
  await navigator.serviceWorker.ready;
  const sub = (await reg.pushManager.getSubscription()) ||
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(publicKey) }));
  await api("/push/subscribe", { method: "POST", body: sub.toJSON() });  // idempotent; also refreshes a stale row
}

const COPY = {
  ask: {
    title: "Allow notifications on this device?",
    text: "EZTrading will notify you when an analysis needs your attention. Your browser will ask you to confirm.",
    ok: "Allow",
  },
  blocked: {
    title: "Notifications are blocked",
    text: "Your browser is blocking notifications for this site. Click the icon left of the address bar → " +
      "Site settings → Notifications → Allow, then click Try again.",
    ok: "Try again",
  },
};

/** Opens the permission popup; resolves true once this device is subscribed, false if the user backs out. */
function askPermission(publicKey) {
  const dialog = $("push-dialog");
  const show = (mode) => {
    $("push-dialog-title").textContent = COPY[mode].title;
    $("push-dialog-text").textContent = COPY[mode].text;
    $("push-allow").textContent = COPY[mode].ok;
  };
  show(Notification.permission === "denied" ? "blocked" : "ask");
  return new Promise((resolve) => {
    const finish = (ok) => {
      $("push-allow").onclick = $("push-later").onclick = dialog.oncancel = null;
      dialog.close();
      resolve(ok);
    };
    $("push-later").onclick = () => finish(false);
    dialog.oncancel = () => finish(false);
    $("push-allow").onclick = async () => {
      const permission = Notification.permission === "default" ? await Notification.requestPermission()
        : Notification.permission;
      if (permission !== "granted") return show("blocked");
      try {
        await subscribe(publicKey);
        finish(true);
      } catch (err) {
        $("push-dialog-text").textContent = `Couldn't register this device: ${err.message}`;
      }
    };
    dialog.showModal();
  });
}

/** Makes sure this device can receive push, asking only when needed. Resolves true when subscribed. */
export async function ensurePush(publicKey) {
  if (!pushSupported()) throw new Error("This browser does not support push notifications");
  if (!publicKey) throw new Error("Push notifications are not configured on the server");
  if (Notification.permission === "granted") {
    await subscribe(publicKey);  // silently (re)subscribe
    return true;
  }
  return askPermission(publicKey);
}
