import { api } from "../api.js";
import { $, busy, esc, money, num, toast } from "../ui.js";
import { emit, state } from "../state.js";

const STATUS_LABEL = { executed: "Executed", ignored: "Ignored", failed: "Failed – retry?", executing: "Placing…" };

// --- style picker -----------------------------------------------------------
export function renderStylePicker() {
  const picker = $("style-picker");
  picker.innerHTML = state.styles.map((s) => `
    <button type="button" role="radio" data-style="${s.key}" aria-checked="${s.key === state.style}"
      class="${s.key === state.style ? "active" : ""}">${esc(s.label)}</button>`).join("");
  const current = state.styles.find((s) => s.key === state.style);
  $("style-desc").textContent = current ? current.description : "";
}

// --- plan -------------------------------------------------------------------
function levels(s) {
  const parts = [];
  if (s.entry_price) parts.push(`Entry ${num(s.entry_price)}`);
  if (s.stop_loss) parts.push(`SL ${num(s.stop_loss)}`);
  if (s.target) parts.push(`Target ${num(s.target)}`);
  if (s.horizon) parts.push(esc(s.horizon));
  return parts.length ? `<p class="small levels">${parts.join(" · ")}</p>` : "";
}

function actions(s) {
  if (s.action === "HOLD") return "";
  if (s.status === "pending" || s.status === "failed") {
    const execute = state.config.orders_enabled === false
      ? `<span class="small muted">Execution disabled — place orders in Kite</span>`
      : `<button class="btn btn-sm" data-execute="${esc(s.id)}" type="button">${s.status === "failed" ? "Retry" : "Execute"}</button>`;
    return `<div class="row end">
      <button class="btn btn-secondary btn-sm" data-ignore="${esc(s.id)}" type="button">Ignore</button>
      ${execute}
    </div>`;
  }
  return `<p class="status-badge ${s.status}">${STATUS_LABEL[s.status] || s.status}</p>`;
}

export function renderPlan(plan) {
  state.plan = plan;
  const body = $("plan-body");
  $("dismiss-btn").classList.toggle("hidden", !plan);
  if (!plan) {
    body.innerHTML = `<p class="muted">No active plan. Pick a style and press Analyze.</p>`;
    return;
  }
  const actionable = plan.suggestions.filter((s) => s.action !== "HOLD");
  const styleLabel = state.styles.find((s) => s.key === plan.style)?.label || plan.style;
  const cards = plan.suggestions.map((s) => `
    <article class="sugg ${s.action} ${s.status}">
      <div class="sugg-head">
        <span><span class="tag">${s.action === "SELL" && s.product === "MIS" ? "SHORT" : s.action}</span> ${esc(s.symbol)}
          <span class="small muted">${s.product}</span></span>
        <span class="num">${s.action === "HOLD" ? "" : `${s.quantity} × ${s.price.toFixed(2)} = ${money(s.amount)}`}</span>
      </div>
      ${levels(s)}
      <p>${esc(s.rationale)}</p>
      <p class="small muted">Confidence ${(s.confidence * 100).toFixed(0)}%</p>
      ${actions(s)}
    </article>`).join("");

  body.innerHTML = `
    <p class="market-view">${esc(plan.market_view)}</p>
    <div class="summary-grid">
      <div class="stat"><span>Style</span><strong>${esc(styleLabel)}</strong></div>
      <div class="stat"><span>Budget</span><strong>${money(plan.budget)}</strong></div>
      <div class="stat"><span>Total buy</span><strong class="pos">${money(plan.total_buy)}</strong></div>
      <div class="stat"><span>Total sell</span><strong class="neg">${money(plan.total_sell)}</strong></div>
      <div class="stat"><span>Unallocated</span><strong>${money(plan.cash_left)}</strong></div>
    </div>
    ${actionable.length ? "" : `<p><strong>Recommendation: take no action right now.</strong></p>`}
    <div class="suggestions">${cards}</div>
    ${plan.warnings.length ? `<details class="warnings"><summary>${plan.warnings.length} adjustment(s) made by the validator</summary><ul>${plan.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></details>` : ""}
    <p class="small muted">Generated ${new Date(plan.generated_at).toLocaleString()} by ${esc(plan.advisor)}</p>`;
}

export async function loadPlan() {
  renderPlan(await api("/plan"));
}

async function analyze() {
  await busy($("analyze-btn"), "Analyzing…", async () => {
    renderPlan(await api("/analyze", { method: "POST", body: { style: state.style } }));
  });
}

async function dismiss() {
  if (!state.plan) return;
  await busy($("dismiss-btn"), "…", async () => {
    await api(`/plans/${state.plan.id}`, { method: "DELETE" });
    renderPlan(null);
    toast("Plan dismissed, no action taken");
  });
}

async function ignore(id, button) {
  await busy(button, "…", async () => {
    await api(`/plans/${state.plan.id}/suggestions/${encodeURIComponent(id)}/ignore`, { method: "POST" });
    await loadPlan();
  });
}

// --- execute dialog -----------------------------------------------------------
let pending = null;

function updateEstimate() {
  const qty = Number($("exec-qty").value) || 0;
  const market = $("exec-type").value === "MARKET";
  $("exec-price-wrap").classList.toggle("hidden", market);
  const price = market ? pending.price : Number($("exec-price").value) || pending.price;
  $("exec-est").textContent = `${money(qty * price)}${market ? " (approx.)" : ""}`;
}

function openExecute(id) {
  const s = state.plan.suggestions.find((x) => x.id === id);
  if (!s) return;
  pending = s;
  const side = s.action === "SELL" && s.product === "MIS" ? "SHORT SELL" : s.action;
  $("execute-title").textContent = `${side} ${s.symbol}`;
  $("execute-summary").innerHTML = `
    <p>Product <strong>${s.product}</strong> (${s.product === "MIS" ? "intraday, auto square-off" : "delivery"}) ·
       Exchange <strong>NSE</strong> · Last price <strong>${num(s.price)}</strong></p>
    ${levels(s)}
    ${s.stop_loss ? `<p class="small muted">Stop-loss and target are not placed automatically. Set them in Kite after the entry fills.</p>` : ""}`;
  $("exec-qty").value = s.quantity;
  $("exec-qty").max = s.quantity;
  $("exec-type").value = "LIMIT";
  $("exec-price").value = (s.entry_price || s.price).toFixed(2);
  $("exec-confirm").checked = false;
  $("exec-error").classList.add("hidden");
  updateEstimate();
  $("execute-dialog").showModal();
}

async function submitExecute(e) {
  e.preventDefault();
  const market = $("exec-type").value === "MARKET";
  const body = {
    quantity: Number($("exec-qty").value),
    order_type: $("exec-type").value,
    price: market ? null : Number($("exec-price").value),
  };
  await busy($("exec-submit"), "Placing…", async () => {
    const order = await api(`/plans/${state.plan.id}/suggestions/${encodeURIComponent(pending.id)}/execute`,
      { method: "POST", body });
    $("execute-dialog").close();
    toast(`Order placed: ${order.side} ${order.quantity} ${order.symbol} (Kite id ${order.broker_order_id}, ${order.status})`, "success");
    await Promise.all([loadPlan(), loadOrders()]);
    emit("wallet-changed");
  }, (err) => {
    $("exec-error").textContent = err.message;
    $("exec-error").classList.remove("hidden");
    loadPlan().catch(() => {});
    loadOrders().catch(() => {});
  });
}

// --- orders -------------------------------------------------------------------
export async function loadOrders() {
  const orders = await api("/orders");
  $("orders-body").innerHTML = orders.length
    ? orders.map((o) => `
      <tr>
        <td>${new Date(o.created_at + "Z").toLocaleString()}</td>
        <td>${esc(o.symbol)}</td>
        <td>${o.side} <span class="small muted">${o.product}</span></td>
        <td class="num">${o.quantity}</td>
        <td>${o.order_type}</td>
        <td class="num">${o.price ? num(o.price) : "MKT"}</td>
        <td title="${esc(o.error || "")}"><span class="status-badge ${o.status === "FAILED" || o.status === "REJECTED" ? "failed" : "executed"}">${esc(o.status)}</span></td>
        <td class="small">${esc(o.broker_order_id || "—")}</td>
      </tr>`).join("")
    : `<tr><td colspan="8" class="muted">No orders yet.</td></tr>`;
}

async function refreshOrders() {
  await busy($("orders-refresh"), "…", async () => {
    const orders = await api("/orders");
    const open = orders.filter((o) => o.broker_order_id && !["COMPLETE", "REJECTED", "CANCELLED", "FAILED"].includes(o.status));
    await Promise.all(open.slice(0, 10).map((o) => api(`/orders/${o.id}/refresh`, { method: "POST" })));
    await loadOrders();
  });
}

export function initPlan() {
  $("style-picker").addEventListener("click", (e) => {
    const key = e.target.closest("[data-style]")?.dataset.style;
    if (key) { state.style = key; renderStylePicker(); }
  });
  $("analyze-btn").addEventListener("click", analyze);
  $("dismiss-btn").addEventListener("click", dismiss);
  $("plan-body").addEventListener("click", (e) => {
    const exec = e.target.closest("[data-execute]");
    const ign = e.target.closest("[data-ignore]");
    if (exec) openExecute(exec.dataset.execute);
    if (ign) ignore(ign.dataset.ignore, ign);
  });
  ["exec-qty", "exec-type", "exec-price"].forEach((id) => $(id).addEventListener("input", updateEstimate));
  $("execute-form").addEventListener("submit", submitExecute);
  $("orders-refresh").addEventListener("click", refreshOrders);
}
