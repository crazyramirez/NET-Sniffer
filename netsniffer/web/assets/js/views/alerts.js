import { api } from "../api.js";
import { emptyState, EVENT_ICON, eventClass, eventText, showError } from "../common.js";
import { fmt, t } from "../i18n.js";
import { S } from "../store.js";
import { confirmDialog, html, ico } from "../ui.js";
import { openDevice } from "./device.js";

let root, events = [], filter = "all";
const GROUPS = {
  security: ["security_issues", "camera_detected", "device_new", "device_blocked", "device_unblocked"],
  devices: ["device_new", "device_online", "device_offline", "device_ip_changed", "device_first_seen"],
  internet: ["internet_down", "internet_up", "gateway_down"],
};

function paint() {
  if (!root) return;
  const list = events.filter((e) => filter === "all" || GROUPS[filter].includes(e.kind));
  const byDay = {};
  list.forEach((e) => { const k = new Date(e.ts * 1000).toDateString(); (byDay[k] ||= []).push(e); });
  root.innerHTML = html`<div class="toolbar">
    <div class="row wrap" style="gap:6px">${["all", "security", "devices", "internet"].map((f) => html`<button class="chip ${filter === f ? "on" : ""}" data-f="${f}">${t(`alerts.f_${f}`)}</button>`)}</div>
    <div class="grow"></div>
    <button class="btn sm" id="read">${ico("check")} ${t("alerts.mark_read")}</button>
    <button class="btn sm danger" id="clear">${ico("trash")} ${t("alerts.clear")}</button></div>
  <div class="card"><div class="card-b">${list.length ? Object.entries(byDay).map(([day, evs]) => html`
    <div class="nav-label" style="padding-left:2px">${fmt.day(evs[0].ts)}</div>
    <div class="list">${evs.map((ev) => { const { title, text } = eventText(ev);
      return html`<div class="li ${ev.device_id ? "click" : ""}" data-dev="${ev.device_id || ""}" style="${ev.read ? "" : "font-weight:600"}">
        <span class="ev-ico ${eventClass(ev)}">${ico(EVENT_ICON[ev.kind] || "info")}</span>
        <div class="li-main"><div class="li-t">${title}</div><div class="li-s">${text}</div></div>
        ${!ev.read && ["warning", "critical"].includes(ev.severity) ? html`<span class="status-dot bad"></span>` : ""}
        <span class="faint" style="font-size:12px;white-space:nowrap">${fmt.time(ev.ts)}</span></div>`; })}</div>`)
    : emptyState("bell", t("alerts.none"), t("alerts.none_d"))}</div></div>`;
}

async function load() {
  try { const r = await api("/events?limit=500"); events = r.events; S.unread = r.unread; paint(); } catch (e) { showError(e); }
}

function render(el) {
  root = el; paint(); load();
  el.onclick = async (e) => {
    const f = e.target.closest("[data-f]"); if (f) { filter = f.dataset.f; return paint(); }
    const d = e.target.closest("[data-dev]"); if (d?.dataset.dev) return openDevice(d.dataset.dev);
    if (e.target.closest("#read")) { await api("/events/read", { method: "POST", body: {} }).catch(showError); events.forEach((x) => (x.read = true)); paint(); }
    if (e.target.closest("#clear")) {
      if (!(await confirmDialog({ title: t("alerts.clear"), text: t("alerts.clear_text"), ok: t("common.delete"), cancel: t("common.cancel"), danger: true }))) return;
      await api("/events", { method: "DELETE" }).catch(showError); events = []; paint();
    }
  };
}
function onEvent(type, data) {
  if (!root) return;
  if (type === "event" && data.id) { events.unshift(data); paint(); }
}
export default { render, onEvent, destroy() { root = null; } };
