import { api } from "../api.js";
import { $, busy, esc, money, num } from "../ui.js";

let ipos = [];
let assessments = {};
let loaded = false;

const fmtDate = (d) => (d ? new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "—");

function render() {
  if (!ipos.length) {
    $("ipo-body").innerHTML = `<p class="muted">No open or upcoming IPOs found.</p>`;
    return;
  }
  $("ipo-body").innerHTML = `<div class="ipo-grid">${ipos.map((i) => {
    const a = assessments[i.symbol];
    return `
    <article class="ipo-card ${a ? a.verdict : ""}">
      <div class="sugg-head">
        <span>${esc(i.name)} <span class="small muted">${esc(i.symbol)}</span></span>
        <span class="badge ${i.status}">${esc(i.status)}</span>
      </div>
      <dl class="facts">
        <div><dt>Dates</dt><dd>${fmtDate(i.issue_start)} – ${fmtDate(i.issue_end)}</dd></div>
        <div><dt>Price band</dt><dd>${i.price_low ? `₹${num(i.price_low)}–${num(i.price_high)}` : "—"}</dd></div>
        <div><dt>Lot</dt><dd>${i.lot_size ? `${i.lot_size} sh (${money(i.min_investment)})` : "—"}</dd></div>
        <div><dt>Category</dt><dd>${esc(i.category)}</dd></div>
        <div><dt>Issue size</dt><dd>${esc(i.issue_size || "—")}</dd></div>
        <div><dt>Subscribed</dt><dd>${i.subscription_times != null ? `${num(i.subscription_times)}×` : "—"}</dd></div>
      </dl>
      ${a ? `
        <p><span class="tag verdict-${a.verdict}">${a.verdict}</span>
          ${a.suggested_lots ? ` · apply for <strong>${a.suggested_lots} lot(s)</strong>` : ""}</p>
        <p class="small">${esc(a.rationale)}</p>
        ${a.risks ? `<p class="small muted"><strong>Risks:</strong> ${esc(a.risks)}</p>` : ""}` : ""}
    </article>`;
  }).join("")}</div>`;
}

export async function loadIpos(force = false) {
  if (loaded && !force) return;
  try {
    ipos = await api("/ipos");
    loaded = true;
    render();
  } catch (e) {
    $("ipo-body").innerHTML = `<p class="muted">${esc(e.message)}</p>`;
  }
}

async function review() {
  await busy($("ipo-review-btn"), "Reviewing…", async () => {
    const r = await api("/ipos/review", { method: "POST" });
    ipos = r.ipos;
    assessments = Object.fromEntries(r.assessments.map((a) => [a.symbol, a]));
    $("ipo-overview").textContent = `${r.overview} (by ${r.advisor}, budget ${money(r.budget)})`;
    $("ipo-overview").classList.remove("hidden");
    render();
  });
}

export function initIpo() {
  $("ipo-refresh").addEventListener("click", () => busy($("ipo-refresh"), "…", () => loadIpos(true)));
  $("ipo-review-btn").addEventListener("click", review);
}
