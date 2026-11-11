import { api } from "./api.js";
import { $ } from "./ui.js";

const ERRORS = {
  google: "Google sign-in failed. Please try again.",
  email: "Your Google account email is not verified.",
  conflict: "Another account already uses this email address.",
};

const VIEWS = ["signin", "signup", "verify", "forgot", "reset"];
let email = "";  // the address the current code was sent to

function message(text, kind = "error") {
  $("login-error").classList.toggle("hidden", kind !== "error" || !text);
  $("login-info").classList.toggle("hidden", kind !== "info" || !text);
  $(kind === "error" ? "login-error" : "login-info").textContent = text || "";
}

function show(view) {
  VIEWS.forEach((v) => $(`pw-${v}`).classList.toggle("hidden", v !== view));
  document.querySelectorAll("[data-email]").forEach((el) => { el.textContent = email; });
  $(`pw-${view}`).querySelector("input")?.focus();
}

const post = (path, body) => api(path, { method: "POST", body, root: true });

// What each form sends, and what happens next.
const HANDLERS = {
  signin: async (f) => {
    email = f.email.value.trim();
    const r = await post("/auth/login", { email, password: f.password.value });
    if (r.next === "verify") {
      message(r.message, "info");
      return show("verify");
    }
    location.href = "/";
  },
  signup: async (f) => {
    email = f.email.value.trim();
    const r = await post("/auth/signup", { name: f.name.value.trim(), email, password: f.password.value });
    message(r.message, "info");
    show("verify");
  },
  verify: async (f) => {
    await post("/auth/verify", { email, code: f.code.value.trim() });
    location.href = "/";
  },
  forgot: async (f) => {
    email = f.email.value.trim();
    const r = await post("/auth/password/forgot", { email });
    message(r.message, "info");
    show("reset");
  },
  reset: async (f) => {
    await post("/auth/password/reset", { email, code: f.code.value.trim(), password: f.password.value });
    location.href = "/";
  },
};

function initPasswordForms() {
  VIEWS.forEach((view) => {
    const form = $(`pw-${view}`);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      message("");
      try {
        await HANDLERS[view](form);
      } catch (ex) {
        message(ex.message);
      } finally {
        btn.disabled = false;
      }
    });
  });
  document.querySelectorAll("[data-go]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    message("");
    show(a.dataset.go);
  }));
  document.querySelector("[data-resend]").addEventListener("click", async (e) => {
    e.preventDefault();
    try {
      message((await post("/auth/otp/resend", { email })).message, "info");
    } catch (ex) {
      message(ex.message);
    }
  });
}

async function init() {
  const err = new URLSearchParams(location.search).get("error");
  if (err) message(ERRORS[err] || "Sign-in failed.");
  const config = await api("/config");
  $("google-btn").classList.toggle("hidden", !config.google_enabled);
  $("pw-auth").classList.toggle("hidden", !config.password_login);
  $("or-divider").classList.toggle("hidden", !(config.google_enabled && config.password_login));
  $("dev-form").classList.toggle("hidden", !config.dev_login);
  $("no-auth").classList.toggle("hidden", config.google_enabled || config.dev_login || config.password_login);
  if (config.password_login) initPasswordForms();

  $("dev-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await post("/auth/dev-login", { email: $("dev-email").value });
      location.href = "/";
    } catch (ex) {
      message(ex.message);
    }
  });
}

init();
