import { api } from "../api.js";
import { $, busy, esc, money, pct, showError, signClass, toast } from "../ui.js";
import { on, state } from "../state.js";

function renderHoldings(p) {
  $("totals").innerHTML = `
    <div><span>Invested</span>${money(p.total_invested)}</div>
    <div><span>Current</span>${money(p.total_value)}</div>
    <div><span>P&amp;L</span><b class="${signClass(p.total_pnl)}">${money(p.total_pnl)} (${pct(p.total_pnl_pct)})</b></div>`;
  $("holdings-body").innerHTML = p.holdings.length
    ? p.holdings.map((h) => `
      <tr>
        <td>${esc(h.symbol)}</td>
        <td class="num">${h.quantity}</td>
        <td class="num">${h.average_price.toFixed(2)}</td>
        <td class="num">${h.last_price.toFixed(2)}</td>
        <td class="num">${money(h.current_value)}</td>
        <td class="num ${signClass(h.pnl)}">${money(h.pnl)}<br><small>${pct(h.pnl_pct)}</small></td>
        <td class="num ${signClass(h.day_change_pct)}">${pct(h.day_change_pct)}</td>
      </tr>`).join("")
    : `<tr><td colspan="7" class="muted">No holdings.</td></tr>`;
  $("holdings-time").textContent = `Updated ${new Date(p.fetched_at).toLocaleTimeString()}`;
}

function holdingsMessage(text) {
  $("totals").innerHTML = "";
  $("holdings-body").innerHTML = `<tr><td colspan="7" class="muted">${esc(text)}</td></tr>`;
}

export async function loadHoldings() {
  const s = state.status;
  if (s && !s.broker_configured) return holdingsMessage("Add your Kite API keys in Settings to see holdings.");
  if (s && !s.broker_connected) return holdingsMessage("Click 'Connect Kite' (top right) to load holdings.");
  try {
    renderHoldings(await api("/portfolio"));
  } catch (e) {
    holdingsMessage(e.message);
    showError(e);
  }
}

function renderWallet(w) {
  $("wallet-saved").textContent = money(w.deployable);
  $("broker-cash").textContent = money(w.broker_cash);
  if (document.activeElement !== $("wallet-input")) $("wallet-input").value = w.deployable || "";
}

export async function loadWallet() {
  renderWallet(await api("/wallet"));
}

export function initPortfolio() {
  $("wallet-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const btn = e.submitter || e.target.querySelector("button");
    busy(btn, "Saving…", async () => {
      renderWallet(await api("/wallet", { method: "PUT", body: { deployable: Number($("wallet-input").value) } }));
      toast("Wallet saved");
    });
  });
  $("refresh-btn").addEventListener("click", () =>
    busy($("refresh-btn"), "Refreshing…", () => Promise.all([loadHoldings(), loadWallet()])));
  on("wallet-changed", () => loadWallet().catch(showError));
  on("status-changed", () => loadHoldings());
}
