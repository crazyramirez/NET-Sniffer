// REST + WebSocket client.
export class ApiError extends Error {
  constructor(status, detail) {
    super(detail?.error || `HTTP ${status}`);
    this.status = status; this.key = detail?.error || "generic"; this.params = detail?.params || {};
  }
}

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => (onUnauthorized = fn);

export async function api(path, { method = "GET", body } = {}) {
  let r;
  try {
    r = await fetch("/api" + path, {
      method, credentials: "same-origin",
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, { error: "offline" });
  }
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json().catch(() => ({})) : await r.text();
  if (r.status === 401 && !path.startsWith("/auth")) onUnauthorized();
  if (!r.ok) throw new ApiError(r.status, data?.detail || {});
  return data;
}

export function connectWS(onMessage, onState) {
  let ws, retry = 0, pingTimer, closedByUs = false;
  const open = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/api/ws`);
    ws.onopen = () => {
      retry = 0; onState?.(true);
      pingTimer = setInterval(() => ws.readyState === 1 && ws.send("ping"), 25000);
    };
    ws.onmessage = (e) => { try { const m = JSON.parse(e.data); if (m.type !== "pong") onMessage(m.type, m.data); } catch { /* ignore */ } };
    ws.onclose = (e) => {
      clearInterval(pingTimer); onState?.(false);
      if (e.code === 4401) { onUnauthorized(); return; }
      if (!closedByUs) setTimeout(open, Math.min(10000, 600 * 2 ** retry++));
    };
  };
  open();
  return { close() { closedByUs = true; ws?.close(); } };
}
