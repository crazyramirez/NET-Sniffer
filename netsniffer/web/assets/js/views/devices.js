import { api } from "../api.js";
import { deviceAvatar, deviceBadges, deviceStatus, deviceSub, emptyState, showError } from "../common.js";
import { fmt, t } from "../i18n.js";
import { TYPES } from "../icons.js";
import { startScan } from "../main.js";
import { S, on } from "../store.js";
import { $, html, ico, openMenu, toast, confirmDialog } from "../ui.js";
import { openDevice } from "./device.js";

let root, offSearch;
const st = { filter: "all", type: "", q: "", sort: "status", dir: 1, view: (() => { try { return localStorage.getItem("ns-view") || "list"; } catch { return "list"; } })() };
const ipNum = (ip) => (ip || "0.0.0.0").split(".").reduce((a, b) => a * 256 + +b, 0);

function filtered() {
  const day = Date.now() / 1000 - 86400, q = st.q.trim().toLowerCase();
  let list = S.devices.filter((d) => {
    if (st.filter === "online" && !d.online) return false;
    if (st.filter === "offline" && d.online) return false;
    if (st.filter === "untrusted" && (d.trusted || d.is_self)) return false;
    if (st.filter === "blocked" && !d.blocked) return false;
    if (st.filter === "new" && !(d.first_seen > day)) return false;
    if (st.type && d.type !== st.type) return false;
    if (q) {
      const hay = [d.display_name, d.ip, d.mac, d.vendor, d.model, d.hostname, d.os, t(`types.${d.type}`), d.notes].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  const key = {
    status: (d) => [d.online ? 0 : 1, d.is_gateway ? 0 : 1, ipNum(d.ip)], name: (d) => [d.display_name.toLowerCase()], ip: (d) => [ipNum(d.ip)],
    vendor: (d) => [(d.vendor || "~").toLowerCase()], type: (d) => [d.type], seen: (d) => [-(d.last_seen || 0)],
  }[st.sort];
  list.sort((a, b) => { const ka = key(a), kb = key(b); for (let i = 0; i < ka.length; i++) { if (ka[i] < kb[i]) return -st.dir; if (ka[i] > kb[i]) return st.dir; } return 0; });
  return list;
}

function counts() {
  const day = Date.now() / 1000 - 86400;
  return {
    all: S.devices.length, online: S.devices.filter((d) => d.online).length, offline: S.devices.filter((d) => !d.online).length,
    untrusted: S.devices.filter((d) => !d.trusted && !d.is_self).length, new: S.devices.filter((d) => d.first_seen > day).length,
    blocked: S.devices.filter((d) => d.blocked).length,
  };
}

function th(key, label, cls = "") {
  const on = st.sort === key;
  return html`<th class="${cls} ${on ? "sorted" : ""}" data-sort="${key}">${label}<span class="sort">${on ? (st.dir > 0 ? "↑" : "↓") : "↕"}</span></th>`;
}

function listView(list) {
  return html`<div class="card" style="overflow:hidden"><div style="overflow-x:auto"><table class="table"><thead><tr>
    ${th("name", t("device.name"))}${th("ip", "IP")}${th("vendor", "MAC", "hide-s")}${th("type", t("device.type"), "hide-s")}${th("status", t("device.status"))}<th style="width:30px"></th>
  </tr></thead><tbody>${list.map((d) => html`<tr data-id="${d.id}">
    <td><div class="dev">${deviceAvatar(d)}<div style="min-width:0"><div class="nm">${d.favorite ? html`<span style="color:var(--warn)">${ico("star")}</span>` : ""}${d.display_name}</div>
      <div class="sb">${deviceSub(d)}</div></div><div class="badges hide-s">${deviceBadges(d)}</div></div></td>
    <td class="mono">${d.ip}</td>
    <td class="mono hide-s faint">${d.mac || "—"}${d.randomized ? html` <span class="badge" title="${t("device.private_mac_hint")}">${t("device.private")}</span>` : ""}</td>
    <td class="hide-s">${t(`types.${d.type || "unknown"}`)}</td>
    <td>${deviceStatus(d)}</td><td class="faint">${ico("chevR")}</td></tr>`)}</tbody></table></div></div>`;
}

function gridView(list) {
  return html`<div class="dev-grid">${list.map((d) => html`<div class="card dev-card" data-id="${d.id}">
    <div class="top">${deviceAvatar(d)}<div style="min-width:0;flex:1"><div class="nm">${d.display_name}</div><div class="faint" style="font-size:12.5px">${deviceSub(d)}</div></div></div>
    <div class="kv"><span>IP</span><span class="mono">${d.ip}</span><span>MAC</span><span class="mono">${d.mac || "—"}</span>
      <span>${t("device.status")}</span><span>${deviceStatus(d)}</span></div>
    <div class="row wrap" style="gap:5px">${deviceBadges(d, { compact: true })}</div></div>`)}</div>`;
}

function paint() {
  if (!root) return;
  const c = counts(), list = filtered();
  const types = [...new Set(S.devices.map((d) => d.type || "unknown"))].sort();
  root.innerHTML = html`
    <div class="toolbar">
      <div class="row wrap" style="gap:6px">${["all", "online", "offline", "untrusted", "new", "blocked"].filter((f) => f !== "blocked" || c.blocked).map((f) =>
        html`<button class="chip ${st.filter === f ? "on" : ""}" data-filter="${f}">${t(`devices.f_${f}`)} <span class="n">${c[f]}</span></button>`)}</div>
      <div class="grow"></div>
      <select class="input" id="type-f" style="width:auto;height:34px"><option value="">${t("devices.all_types")}</option>
        ${types.map((x) => html`<option value="${x}" ${st.type === x ? "selected" : ""}>${t(`types.${x}`)}</option>`)}</select>
      <div class="seg"><button class="${st.view === "list" ? "on" : ""}" data-view="list" aria-label="list">${ico("list")}</button><button class="${st.view === "grid" ? "on" : ""}" data-view="grid" aria-label="grid">${ico("grid")}</button></div>
      <button class="btn icon sm" id="more" aria-label="${t("common.more")}">${ico("more")}</button>
    </div>
    ${st.q ? html`<div class="faint" style="margin:-6px 0 12px">${t("devices.results", { count: list.length, q: st.q })}</div>` : ""}
    ${list.length ? (st.view === "grid" ? gridView(list) : listView(list)) :
      S.devices.length ? html`<div class="card">${emptyState("search", t("devices.none_match"), t("devices.none_match_hint"))}</div>` :
        html`<div class="card">${emptyState("radar", t("dash.no_devices"), t("dash.scan_hint"), html`<button class="btn primary" data-scan>${ico("radar")} ${t("scan.button")}</button>`)}</div>`}`;
}

function bind() {
  root.onclick = async (e) => {
    const f = e.target.closest("[data-filter]"); if (f) { st.filter = f.dataset.filter; return paint(); }
    const v = e.target.closest("[data-view]"); if (v) { st.view = v.dataset.view; try { localStorage.setItem("ns-view", st.view); } catch { /* */ } return paint(); }
    const s = e.target.closest("[data-sort]"); if (s) { if (st.sort === s.dataset.sort) st.dir *= -1; else { st.sort = s.dataset.sort; st.dir = 1; } return paint(); }
    const row = e.target.closest("[data-id]"); if (row) return openDevice(row.dataset.id);
    if (e.target.closest("[data-scan]")) return startScan();
    if (e.target.closest("#more")) {
      openMenu(e.target.closest("#more"), [
        { label: t("devices.deep_scan"), icon: "radar", action: () => startScan(true) },
        { label: t("devices.trust_all"), icon: "shieldCheck", action: trustAll },
        { label: t("devices.export_csv"), icon: "download", action: () => (location.href = "/api/export/devices.csv") },
        { sep: true },
        { label: t("devices.forget_offline"), icon: "trash", action: forgetOffline },
      ]);
    }
  };
  root.onchange = (e) => { if (e.target.id === "type-f") { st.type = e.target.value; paint(); } };
}

async function trustAll() {
  if (!(await confirmDialog({ title: t("devices.trust_all"), text: t("devices.trust_all_text"), ok: t("common.confirm"), cancel: t("common.cancel") }))) return;
  try { await api("/devices/trust-all", { method: "POST" }); S.devices.forEach((d) => (d.trusted = true)); paint(); toast({ kind: "ok", title: t("devices.trusted_ok") }); }
  catch (e) { showError(e); }
}

async function forgetOffline() {
  const off = S.devices.filter((d) => !d.online && !d.is_self);
  if (!off.length) return toast({ title: t("devices.no_offline") });
  if (!(await confirmDialog({ title: t("devices.forget_offline"), text: t("devices.forget_offline_text", { count: off.length }), ok: t("common.delete"), cancel: t("common.cancel"), danger: true }))) return;
  for (const d of off) await api(`/devices/${encodeURIComponent(d.id)}`, { method: "DELETE" }).catch(() => {});
  S.devices = S.devices.filter((d) => d.online || d.is_self); paint();
}

function render(el) {
  root = el;
  st.q = $("#gsearch")?.value || "";
  if (location.hash.includes("?new")) st.filter = "new";
  paint(); bind();
  offSearch?.(); offSearch = on("search", (q) => { st.q = q || ""; paint(); });
}

let raf = false;
function onEvent(type) {
  if (!root || !["devices", "device", "resync"].includes(type) || raf) return;
  raf = true;
  requestAnimationFrame(() => { raf = false; if (root && document.body.contains(root)) { const sc = $("#content").scrollTop; paint(); $("#content").scrollTop = sc; } });
}

export default { render, onEvent, destroy() { root = null; offSearch?.(); offSearch = null; } };
export { fmt };
