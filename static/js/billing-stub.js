// The stub PSP's "hosted payment page". A real provider replaces this page entirely.
import { api } from "./api.js";
import { $ } from "./ui.js";

const orderId = new URLSearchParams(location.search).get("order");

async function complete(paid) {
  try {
    await api("/billing/stub/complete", { method: "POST", body: { order_id: orderId, paid } });
    location.href = `/billing.html?order=${encodeURIComponent(orderId)}`;
  } catch (ex) {
    $("stub-error").textContent = ex.message;
    $("stub-error").classList.remove("hidden");
  }
}

async function init() {
  const order = await api(`/billing/orders/${encodeURIComponent(orderId)}`);
  $("stub-amount").textContent = `₹${order.amount_inr}` + (order.coupon ? ` (coupon ${order.coupon})` : "");
  $("stub-pay").addEventListener("click", () => complete(true));
  $("stub-fail").addEventListener("click", () => complete(false));
}

init().catch((ex) => {
  $("stub-error").textContent = ex.message;
  $("stub-error").classList.remove("hidden");
});
