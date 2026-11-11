// Fetch wrapper: JSON in/out, CSRF header, typed errors, redirect to login on 401.

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.kiteLoginRequired = Boolean(body?.kite_login_required);
    this.authRequired = Boolean(body?.auth_required);
  }
}

export async function api(path, { method = "GET", body, root = false } = {}) {
  const res = await fetch(root ? path : `/api${path}`, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (data.auth_required && !location.pathname.endsWith("login.html")) {
      location.href = "/login.html";
    }
    let detail = data.detail;
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join("; ");
    throw new ApiError(detail || res.statusText, res.status, data);
  }
  return data;
}
