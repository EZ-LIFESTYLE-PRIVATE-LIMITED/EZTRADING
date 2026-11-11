import { api } from "../api.js";
import { $, busy, esc, showError, toast } from "../ui.js";
import { emit, state } from "../state.js";
import { ensurePush, pushStatus } from "../push.js";

function fill(s) {
  state.settings = s;
  $("kite-redirect").textContent = s.kite_redirect_url;
  $("kite-hint").textContent = s.credentials.kite || "none";
  document.querySelectorAll(".key-form").forEach((form) => {
    const hint = s.credentials[form.dataset.kind];
    const server = s.server_keys.includes(form.dataset.kind);
    form.querySelector("[data-hint]").textContent = hint ? `(saved ${hint})`
      : server && s.server_keys_allowed ? "(using server key)" : server ? "(server key: Premium only)" : "(not set)";
  });
  $("ai-premium-note").classList.toggle("hidden", s.server_keys_allowed || !s.server_keys.length);
  $("set-style").innerHTML = styleOptions(s.default_style);
  $("set-push").checked = s.push_enabled;
  $("set-telegram").checked = s.telegram_enabled;
  $("telegram-state").textContent = s.telegram_linked ? "Connected" : "Not connected";
  $("telegram-unlink").classList.toggle("hidden", !s.telegram_linked);
  if (s.telegram_linked) $("telegram-manual").classList.add("hidden");
  $("telegram-link").classList.toggle("hidden", !state.config.telegram_enabled);
  syncPushState();
}

// --- auto-analysis schedules ------------------------------------------------------
const styleOptions = (selected) => state.styles.map((st) =>
  `<option value="${st.key}" ${st.key === selected ? "selected" : ""}>${esc(st.label)}</option>`).join("");
const minInterval = (styleKey) => state.styles.find((x) => x.key === styleKey)?.min_auto_interval_min ?? 5;

function scheduleRow(sc) {
  const at = sc.next_run_at ? new Date(sc.next_run_at + "Z") : null;  // API times are naive UTC
  const next = !sc.enabled ? "paused"
    : at && at > new Date() ? `next ${at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
    : "runs at the next market-hours tick";
  return `
    <div class="schedule-row ${sc.enabled ? "" : "off"}" data-id="${sc.id}">
      <label class="check"><input type="checkbox" data-field="enabled" ${sc.enabled ? "checked" : ""} aria-label="Enabled"></label>
      <select data-field="style" aria-label="Style">${styleOptions(sc.style)}</select>
      <label class="inline-label">every <input type="number" data-field="interval_min" value="${sc.interval_min}"
        min="${minInterval(sc.style)}" step="5" aria-label="Interval in minutes"> min</label>
      <span class="small muted grow">${esc(next)}</span>
      <button type="button" class="btn btn-secondary btn-sm" data-delete>Remove</button>
    </div>`;
}

let schedules = [];

async function loadSchedules() {
  const list = schedules = await api("/schedules");
  $("schedule-list").innerHTML = list.length
    ? list.map(scheduleRow).join("")
    : `<p class="small muted">No schedules yet. Auto-analysis is off.</p>`;
}

async function updateSchedule(row, field, input) {
  const value = field === "enabled" ? input.checked : field === "interval_min" ? Number(input.value) : input.value;
  const body = { [field]: value };
  if (field === "style") {  // keep the interval valid for the new style
    const interval = row.querySelector('[data-field="interval_min"]');
    body.interval_min = Math.max(Number(interval.value), minInterval(value));
  }
  try {
    await api(`/schedules/${row.dataset.id}`, { method: "PUT", body });
    toast("Schedule saved");
  } catch (err) {
    showError(err);
  }
  await loadSchedules().catch(showError);
}

function initSchedules() {
  $("schedule-list").addEventListener("change", (e) => {
    const row = e.target.closest(".schedule-row");
    if (row && e.target.dataset.field) updateSchedule(row, e.target.dataset.field, e.target);
  });
  $("schedule-list").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-delete]");
    if (!btn) return;
    busy(btn, "…", async () => {
      await api(`/schedules/${btn.closest(".schedule-row").dataset.id}`, { method: "DELETE" });
      await loadSchedules();
    });
  });
  $("sched-new-style").addEventListener("change", (e) => {
    const input = $("sched-new-interval");
    input.min = minInterval(e.target.value);
    input.value = Math.max(Number(input.value) || 0, Number(input.min));
  });
  $("schedule-add").addEventListener("submit", (e) => {
    e.preventDefault();
    const style = $("sched-new-style").value;
    const interval = Number($("sched-new-interval").value);
    if (schedules.some((sc) => sc.style === style && sc.interval_min === interval)) {
      const label = state.styles.find((x) => x.key === style)?.label || style;
      showError(new Error(`You already have a ${label} schedule every ${interval} min`));
      return;
    }
    busy(e.submitter, "Adding…", async () => {
      await api("/schedules", { method: "POST", body: { style, interval_min: interval } });
      toast("Schedule added", "success");
      await loadSchedules();
    });
  });
}

function resetNewScheduleForm() {
  const style = state.settings?.default_style || state.styles[0].key;
  $("sched-new-style").innerHTML = styleOptions(style);
  $("sched-new-interval").min = minInterval(style);
  $("sched-new-interval").value = Math.max(minInterval(style), 15);
}

const PUSH_STATE = {
  on: ["On for this device", "ok"],
  off: ["Off for this device", ""],
  blocked: ["Blocked in browser settings", "warn"],
  unsupported: ["Not supported in this browser", ""],
};

async function syncPushState() {
  const el = $("push-state");
  if (!state.config.push_public_key) {
    el.textContent = "Not configured on the server";
    el.className = "small muted";
    return;
  }
  const [text, tone] = PUSH_STATE[await pushStatus()];
  el.textContent = text;
  el.className = `small state-chip ${tone}`;
}

/** Makes sure this device is subscribed when push is on; false if the user declined the popup. */
async function pushReady() {
  const ok = await ensurePush(state.config.push_public_key).finally(syncPushState);
  return ok;
}

async function save(patch, message = "Settings saved") {
  fill(await api("/settings", { method: "PUT", body: patch }));
  toast(message);
  emit("settings-changed");
}

export async function openSettings() {
  fill(await api("/settings"));
  resetNewScheduleForm();
  await loadSchedules();
  $("settings-dialog").showModal();
}

export function initSettings() {
  $("copy-redirect").addEventListener("click", async () => {
    await navigator.clipboard.writeText($("kite-redirect").textContent).catch(() => {});
    toast("Redirect URL copied");
  });

  $("kite-form").addEventListener("submit", (e) => {
    e.preventDefault();
    busy(e.submitter, "Saving…", async () => {
      fill(await api("/credentials/kite", { method: "PUT",
        body: { api_key: $("kite-key").value, api_secret: $("kite-secret").value } }));
      $("kite-key").value = "";
      $("kite-secret").value = "";
      toast("Kite keys saved. Now click 'Connect Kite'.", "success");
      emit("settings-changed");
    });
  });
  $("kite-delete").addEventListener("click", (e) => busy(e.target, "…", async () => {
    fill(await api("/credentials/kite", { method: "DELETE" }));
    emit("settings-changed");
  }));

  document.querySelectorAll(".key-form").forEach((form) => {
    const kind = form.dataset.kind;
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const input = form.querySelector("input");
      busy(e.submitter, "Saving…", async () => {
        fill(await api(`/credentials/${kind}`, { method: "PUT", body: { api_key: input.value } }));
        input.value = "";
        toast("API key saved", "success");
        emit("settings-changed");
      });
    });
    form.querySelector("[data-delete]").addEventListener("click", (e) => busy(e.target, "…", async () => {
      fill(await api(`/credentials/${kind}`, { method: "DELETE" }));
      emit("settings-changed");
    }));
  });

  $("set-style").addEventListener("change", (e) =>
    save({ default_style: e.target.value }, "Default style saved").catch(showError));
  initSchedules();

  $("set-push").addEventListener("change", async (e) => {
    const on = e.target.checked;
    try {
      if (on && !(await pushReady())) {  // permission popup + subscribe this browser first
        e.target.checked = false;
        return;
      }
      await save({ push_enabled: on });
      if (on) toast("Push notifications enabled on this device", "success");
    } catch (err) {
      e.target.checked = !on;
      showError(err);
    }
  });
  $("set-telegram").addEventListener("change", () => save({ telegram_enabled: $("set-telegram").checked }).catch(showError));
  $("telegram-link").addEventListener("click", (e) => busy(e.target, "…", async () => {
    const { url } = await api("/telegram/link", { method: "POST" });
    // The t.me deep link only works where the Telegram app is installed, so show the code to send by hand too.
    const link = new URL(url);
    const bot = link.pathname.replace(/^\//, "");
    $("telegram-bot").textContent = "@" + bot;
    $("telegram-cmd").textContent = `/start ${link.searchParams.get("start")}`;
    $("telegram-open-web").href = `https://web.telegram.org/k/#@${encodeURIComponent(bot)}`;
    $("telegram-open-app").href = url;
    $("telegram-manual").classList.remove("hidden");
  }));
  $("telegram-copy").addEventListener("click", async () => {
    await navigator.clipboard.writeText($("telegram-cmd").textContent).catch(() => {});
    toast("Copied. Paste it in the chat with the bot and send.");
  });
  $("telegram-unlink").addEventListener("click", (e) => busy(e.target, "…", () =>
    save({ unlink_telegram: true }, "Telegram disconnected")));
  $("notify-test").addEventListener("click", (e) => busy(e.target, "Sending…", async () => {
    // With push on, make sure this device can receive it (asks for permission if needed) before sending.
    if ($("set-push").checked && state.config.push_public_key && (await pushStatus()) !== "unsupported") {
      await pushReady().catch(showError);
    }
    const { channels } = await api("/notifications/test", { method: "POST" });
    toast(channels.length ? `Sent via ${channels.join(" and ")}`
      : "No channel is set up yet. Tick Browser push or connect Telegram.");
  }));
}
