// App shell: session, top bar (tabs, advisor dropdown, Kite status, user menu), wiring of views.
import { api } from "./api.js";
import { $, esc, setErrorHandler, showError, toast } from "./ui.js";
import { emit, on, state } from "./state.js";
import { initPortfolio, loadWallet } from "./views/portfolio.js";
import { initPlan, loadOrders, loadPlan, renderStylePicker } from "./views/plan.js";
import { initIpo, loadIpos } from "./views/ipo.js";
import { initSettings, openSettings } from "./views/settings.js";

setErrorHandler((e) => {
  if (e.kiteLoginRequired) loadStatus().catch(() => {});
  toast(e.message, "error");
});

// --- status / kite ------------------------------------------------------------
async function loadStatus() {
  state.status = await api("/status");
  const pill = $("kite-pill");
  const s = state.status;
  pill.textContent = !s.broker_configured ? "Set up Kite" : s.broker_connected ? "Kite connected" : "Connect Kite";
  pill.className = `pill ${s.broker_connected ? "ok" : "bad"}`;
  emit("status-changed");
}

function onKitePill() {
  const s = state.status;
  if (!s?.broker_configured) return openSettings().catch(showError);
  if (!s.broker_connected) location.href = "/auth/kite/login";
}

// --- advisor dropdown -------------------------------------------------------------
async function loadAdvisors() {
  const [options, settings] = await Promise.all([api("/advisors"), api("/settings")]);
  state.settings = settings;
  $("advisor-select").innerHTML = options.map((o) => {
    const note = o.key_source === "premium" ? " 🔒 Premium" : o.available ? (o.key_source === "user" ? " (your key)" : "")
      : " (needs key)";
    return `<option value="${o.id}" ${o.id === settings.advisor_id ? "selected" : ""} ${o.available ? "" : "disabled"}>${esc(o.label + note)}</option>`;
  }).join("");
}

async function onAdvisorChange(e) {
  try {
    state.settings = await api("/settings", { method: "PUT", body: { advisor_id: e.target.value } });
    toast(`Advisor: ${e.target.selectedOptions[0].textContent}`);
  } catch (err) {
    showError(err);
    loadAdvisors().catch(() => {});
  }
}

// --- tabs & menu ----------------------------------------------------------------
function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $("tab-portfolio").classList.toggle("hidden", name !== "portfolio");
  $("tab-ipo").classList.toggle("hidden", name !== "ipo");
  if (name === "ipo") loadIpos();
}

function initChrome() {
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  $("advisor-select").addEventListener("change", onAdvisorChange);
  $("kite-pill").addEventListener("click", onKitePill);

  const menu = $("user-menu");
  $("avatar-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    menu.classList.toggle("hidden");
    $("avatar-btn").setAttribute("aria-expanded", String(!menu.classList.contains("hidden")));
  });
  document.addEventListener("click", () => menu.classList.add("hidden"));
  menu.addEventListener("click", (e) => e.stopPropagation());  // keep the menu open while picking a theme
  document.querySelectorAll("button[data-theme-choice]").forEach((b) => b.addEventListener("click", () => {
    window.eztTheme.set(b.dataset.themeChoice);
    syncThemeButtons();
  }));
  syncThemeButtons();
  $("open-settings").addEventListener("click", () => {
    menu.classList.add("hidden");
    openSettings().catch(showError);
  });
  $("logout-btn").addEventListener("click", async () => {
    await api("/auth/logout", { method: "POST", root: true }).catch(() => {});
    location.href = "/login.html";
  });
  document.querySelectorAll("dialog [data-close]").forEach((b) =>
    b.addEventListener("click", () => b.closest("dialog").close()));
}

// Two letters so a lone "I" or "l" can't be mistaken for a divider: "Karan Dhiman" -> "KD", "karan" -> "Ka".
function initials(name, email) {
  const words = (name || email.split("@")[0]).split(/[\s._-]+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  const w = words[0] || "?";
  return w[0].toUpperCase() + (w[1] || "").toLowerCase();
}

function renderUser(me) {
  const btn = $("avatar-btn");
  btn.classList.toggle("has-img", Boolean(me.picture));
  btn.innerHTML = me.picture
    ? `<img src="${esc(me.picture)}" alt="" referrerpolicy="no-referrer">`
    : esc(initials(me.name, me.email));
  btn.title = me.email;
  btn.setAttribute("aria-label", `Account menu for ${me.email}`);
  $("user-email").textContent = me.email;
  const badge = $("plan-badge");
  badge.textContent = me.premium.active ? "Premium" : me.premium.enforced ? "Free" : "Dev";
  badge.classList.toggle("premium", me.premium.active);
}

function syncThemeButtons() {
  const choice = window.eztTheme.get();
  document.querySelectorAll("button[data-theme-choice]").forEach((b) =>
    b.classList.toggle("active", b.dataset.themeChoice === choice));
}

function handleKiteRedirect() {
  const params = new URLSearchParams(location.search);
  const kite = params.get("kite");
  if (!kite) return;
  toast(kite === "connected" ? "Kite connected" : "Kite login failed or was cancelled", kite === "connected" ? "success" : "error");
  history.replaceState(null, "", "/");
}

// --- boot -----------------------------------------------------------------------
async function init() {
  initChrome();
  initPortfolio();
  initPlan();
  initIpo();
  initSettings();

  state.me = await api("/me");  // redirects to login if not signed in
  renderUser(state.me);
  const [config, styles] = await Promise.all([api("/config"), api("/styles")]);
  state.config = config;
  state.styles = styles;
  await loadAdvisors();
  state.style = state.settings.default_style;
  renderStylePicker();
  handleKiteRedirect();

  on("settings-changed", () => {
    loadAdvisors().catch(showError);
    loadStatus().catch(showError);
  });

  await Promise.all([
    loadStatus(),
    loadWallet(),
    loadPlan(),
    loadOrders(),
  ]).catch(showError);  // holdings load on "status-changed"
}

init().catch(showError);
