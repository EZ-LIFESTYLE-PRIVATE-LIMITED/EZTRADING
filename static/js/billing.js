// Premium page: current status, coupon quote, and checkout (provider-agnostic: we just follow redirect_url).
import { api } from "./api.js";
import { $ } from "./ui.js";

let info = null;
let quote = null;

const date = (iso) => new Date(iso + "Z").toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });

function error(text) {
  $("billing-error").textContent = text || "";
  $("billing-error").classList.toggle("hidden", !text);
}

function renderStatus() {
  const p = info.premium;
  $("billing-status").textContent = p.active
    ? `You have Premium until ${date(p.until)}. Buying again adds ${p.period_days} days after that.`
    : p.enforced ? "You're on the free plan." : "Premium isn't required on this server: everyone can use the server's AI keys.";
}

function renderQuote() {
  $("quote").textContent = quote.coupon ? `${quote.coupon}: ${quote.summary}` : "";
  const free = quote.free_days > 0 || quote.total_inr === 0;
  const blocked = !free && !info.payments_available;
  $("payments-off").classList.toggle("hidden", !blocked);
  $("pay-btn").disabled = blocked;
  $("pay-btn").textContent = quote.free_days > 0 ? `Activate ${quote.free_days} free days`
    : quote.total_inr === 0 ? "Activate Premium" : `Pay ₹${quote.total_inr}`;
}

async function refreshQuote(coupon) {
  quote = await api("/billing/quote", { method: "POST", body: { coupon: coupon || null } });
  renderQuote();
}

async function showReturnedOrder() {
  const order = new URLSearchParams(location.search).get("order");
  if (!order) return;
  history.replaceState(null, "", "/billing.html");
  const o = await api(`/billing/orders/${encodeURIComponent(order)}`).catch(() => null);
  if (o?.status === "failed") error("The payment didn't go through. You haven't been charged.");
}

async function init() {
  info = await api("/billing");
  $("plan-price").textContent = `₹${info.price_inr}`;
  $("plan-period").textContent = `/ ${info.period_days} days`;
  renderStatus();
  await showReturnedOrder();
  await refreshQuote(null);

  $("coupon-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    error("");
    try {
      await refreshQuote($("coupon").value.trim());
    } catch (ex) {
      error(ex.message);
      await refreshQuote(null);
    }
  });

  $("pay-btn").addEventListener("click", async () => {
    error("");
    $("pay-btn").disabled = true;
    try {
      const r = await api("/billing/checkout", { method: "POST", body: { coupon: quote.coupon } });
      if (r.status === "redirect") {
        location.href = r.redirect_url;
        return;
      }
      info = await api("/billing");
      renderStatus();
      $("coupon").value = "";
      await refreshQuote(null);
    } catch (ex) {
      error(ex.message);
    } finally {
      $("pay-btn").disabled = false;
      renderQuote();
    }
  });
}

init().catch((ex) => error(ex.message));
