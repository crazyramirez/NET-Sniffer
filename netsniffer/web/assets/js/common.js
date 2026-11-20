// Shared view fragments and actions.
import { api } from "./api.js";
import { fmt, t } from "./i18n.js";
import { avatar } from "./icons.js";
import { S, can } from "./store.js";
import { html, ico, openModal, raw, toast, loadingBtn } from "./ui.js";

export const PRO_LIST = ["audit", "cameras", "blocking", "parental", "remote", "notifications", "watcher", "history", "export"];

export function showError(e) {
  if (e?.status === 402) return upgradeModal(e.params?.feature);
  const key = e?.key || "generic";
  const detail = e?.params?.detail ? String(e.params.detail).replace(/^[a-z_]+:/, "") : "";
  toast({ kind: "error", title: t("errors.title"), text: (t(`errors.${key.split(":")[0]}`, e?.params || {}) + (detail ? ` — ${detail}` : "")).trim() });
}

export function planBadge() {
  const p = S.license?.plan;
  if (p === "pro") return html`<span class="badge pro">${ico("crown")} PRO</span>`;
  if (p === "trial") return html`<span class="badge accent">${t("plan.trial")}</span>`;
  return html`<span class="badge">${t("plan.free")}</span>`;
}

export function proLock(feature, inner, { compact = false } = {}) {
  if (can(feature)) return inner;
  return html`<div class="locked">${inner}<div class="lock-overlay"><div class="lock-box">
    <div class="ico">${ico("crown")}</div><h4>${t("pro.locked_title")}</h4>
    ${compact ? "" : html`<p>${t(`pro.features.${feature}`)}</p>`}
    <button class="btn pro" data-upgrade="${feature}">${ico("sparkles")} ${t("pro.upgrade")}</button></div></div></div>`;
}

export function upgradeModal(feature) {
  const feats = PRO_LIST.map((f) => html`<div class="onb-feat">${ico("check")}<div><b>${t(`pro.names.${f}`)}</b><div class="faint">${t(`pro.features.${f}`)}</div></div></div>`);
  openModal({
    title: t("pro.title"), desc: feature ? t(`pro.features.${feature}`) : t("pro.subtitle"), wide: true, iconName: "crown",
    body: html`<div class="onb-feats">${feats}</div>
      <div class="sep"></div>
      <div class="field"><label>${t("license.enter")}</label>
      <div class="row"><input class="input mono" id="lic-key" placeholder="NS1.xxxxxxxx.xxxxxxxx" autocomplete="off" spellcheck="false">
      <button class="btn primary" id="lic-save">${t("license.activate")}</button></div>
      <div class="hint">${S.license.plan === "trial" ? t("license.trial_left", { count: S.license.trial_days_left }) : t("license.hint")}</div></div>`,
    onMount: (el, close) => {
      el.querySelector("#lic-save").onclick = async (ev) => {
        loadingBtn(ev.currentTarget, true);
        try {
          S.license = await api("/license", { method: "POST", body: { key: el.querySelector("#lic-key").value } });
          toast({ kind: "ok", title: t("license.activated") }); close(); location.hash = location.hash || "#/dashboard"; window.dispatchEvent(new Event("ns:rerender"));
        } catch (e) { showError(e); } finally { loadingBtn(ev.currentTarget, false); }
      };
    },
  });
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
