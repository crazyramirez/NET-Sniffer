// Shared view fragments and actions.
import { fmt, t } from "./i18n.js";
import { avatar } from "./icons.js";
import { html, ico, raw, toast } from "./ui.js";

export function showError(e) {
  const key = e?.key || "generic";
  const detail = e?.params?.detail ? String(e.params.detail).replace(/^[a-z_]+:/, "") : "";
  toast({ kind: "error", title: t("errors.title"), text: (t(`errors.${key.split(":")[0]}`, e?.params || {}) + (detail ? ` — ${detail}` : "")).trim() });
}

export function deviceSub(d) {
  const parts = [];
  if (d.model && d.vendor && !d.model.includes(d.vendor)) parts.push(`${d.vendor} ${d.model}`);
  else if (d.model) parts.push(d.model); else if (d.vendor) parts.push(d.vendor);
  else if (d.randomized) parts.push(t("device.private_mac"));
  else parts.push(t("device.unknown_vendor"));
  return parts.join(" · ");
}

export function deviceBadges(d, { compact = false } = {}) {
  const b = [];
  if (d.is_self) b.push(html`<span class="badge accent">${t("device.this_device")}</span>`);
  if (d.is_gateway) b.push(html`<span class="badge info">${t("device.gateway")}</span>`);
  if (d.blocked) b.push(html`<span class="badge danger">${ico("ban")} ${t("device.blocked")}</span>`);
  if (!d.trusted && !d.is_self) b.push(html`<span class="badge warn">${t("device.untrusted")}</span>`);
  if (!compact && d.first_seen && Date.now() / 1000 - d.first_seen < 86400 && !d.is_self) b.push(html`<span class="badge ok">${t("device.new")}</span>`);
  return b;
}

export function deviceStatus(d) {
  if (d.online) return html`<span class="row" style="gap:8px"><span class="status-dot on"></span>${t("device.online")}</span>`;
  return html`<span class="row faint" style="gap:8px"><span class="status-dot off"></span>${fmt.ago(d.last_seen)}</span>`;
}

export const deviceAvatar = (d, cls = "") => raw(avatar(d.type, cls, !d.online));

export function eventText(ev) {
  const p = { ...(ev.params || {}) };
  return { title: t(`events.${ev.kind}.title`, p), text: t(`events.${ev.kind}.text`, p) };
}
export const EVENT_ICON = {
  device_new: "radar", device_first_seen: "radar", device_online: "power", device_offline: "power", device_ip_changed: "refresh",
  internet_down: "globe", internet_up: "globe", gateway_down: "t_router", security_issues: "shieldAlert", camera_detected: "t_camera",
  device_blocked: "ban", device_unblocked: "unlock", update_installed: "download",
};
export function eventClass(ev) {
  if (ev.kind === "internet_up" || ev.kind === "device_online") return "ok";
  return ev.severity === "critical" ? "critical" : ev.severity === "warning" ? "warning" : "info";
}

export function emptyState(iconName, title, text, action = "") {
  return html`<div class="empty"><div class="ico">${ico(iconName)}</div><h4>${title}</h4><div>${text}</div>${action ? html`<div style="margin-top:14px">${action}</div>` : ""}</div>`;
}
