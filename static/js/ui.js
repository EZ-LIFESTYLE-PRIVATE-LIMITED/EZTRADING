// Small shared UI helpers (DRY across views).

export const $ = (id) => document.getElementById(id);

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
export const money = (v) => (v === null || v === undefined ? "—" : inr.format(v));
export const pct = (v) => `${v > 0 ? "+" : ""}${Number(v).toFixed(2)}%`;
export const num = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 }));
export const signClass = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "");
export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let toastTimer;
export function toast(message, kind = "info") {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 6000);
}

// Runs fn while the button shows a busy label; errors become toasts.
export async function busy(button, label, fn, onError) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try {
    return await fn();
  } catch (e) {
    (onError || defaultError)(e);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

let errorHandler = (e) => toast(e.message, "error");
export const setErrorHandler = (fn) => { errorHandler = fn; };
const defaultError = (e) => errorHandler(e);
export const showError = (e) => errorHandler(e);

export function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}
