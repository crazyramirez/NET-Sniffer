import { api } from "../api.js";
import { deviceAvatar, deviceBadges, deviceSub, emptyState, showError } from "../common.js";
import { fmt, t } from "../i18n.js";
import { avatar, TYPE_COLORS, typeIcon } from "../icons.js";
import { startScan } from "../main.js";
import { S, on, upsertDevice } from "../store.js";
import { $, html, ico, openMenu, raw, toast, confirmDialog } from "../ui.js";
import { openDevice } from "./device.js";

let root, offSearch;
const st = { filter: "all", type: "", q: "", sort: "status", dir: 1, view: (() => { try { return localStorage.getItem("ns-view") || "list"; } catch { return "list"; } })() };
const ipNum = (ip) => (ip || "0.0.0.0").split(".").reduce((a, b) => a * 256 + +b, 0);
const color = (d) => TYPE_COLORS[d.type] || TYPE_COLORS.unknown;

function filtered() {
  const day = Date.now() / 1000 - 86400, q = st.q.trim().toLowerCase();
  const list = S.devices.filter((d) => {
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
    vendor: (d) => [(d.vendor || "~").toLowerCase()], type: (d) => [t(`types.${d.type}`)], seen: (d) => [d.online ? 0 : 1, -(d.last_seen || 0)],
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

// ------------------------------------------------------------------ building blocks
const avatarWithStatus = (d, cls = "") => html`<span class="av-wrap">${deviceAvatar(d, cls)}<i class="av-dot ${d.online ? "on" : ""}"></i></span>`;
const seen = (d) => d.online ? html`<span class="live"><i></i>${t("device.online")}</span>` : html`<span class="faint">${fmt.ago(d.last_seen)}</span>`;
const typePill = (d) => html`<span class="type-pill" style="--c:${color(d)}">${raw(typeIcon(d.type))}${t(`types.${d.type || "unknown"}`)}</span>`;
const favBtn = (d) => html`<button class="fav-btn ${d.favorite ? "on" : ""}" data-fav="${d.id}" aria-label="${t("device.favorite")}" title="${t("device.favorite_hint")}">${ico("star")}</button>`;

function sortHead(key, label, cls = "") {
  const active = st.sort === key;
  return html`<button class="dl-sort ${cls} ${active ? "on" : ""}" data-sort="${key}">${label}<span>${active ? (st.dir > 0 ? "↑" : "↓") : ""}</span></button>`;
}

function row(d) {
  return html`<div class="dl-row ${d.online ? "" : "is-off"}" data-id="${d.id}" tabindex="0" style="--c:${color(d)}">
    <div class="dl-main">${avatarWithStatus(d)}
      <div class="dl-txt"><div class="dl-name"><span class="dl-title">${d.display_name}</span><span class="dl-badges">${deviceBadges(d)}</span></div>
        <div class="dl-sub">${deviceSub(d)}</div></div></div>
    <div class="dl-type hide-s">${typePill(d)}</div>
    <div class="dl-addr"><span class="ip-pill mono">${d.ip}</span>
      <span class="dl-mac mono hide-s">${d.mac || "—"}${d.randomized ? html` · <span title="${t("device.private_mac_hint")}">${t("device.private")}</span>` : ""}</span></div>
    <div class="dl-seen hide-s">${seen(d)}</div>
    <div class="dl-act">${favBtn(d)}<span class="dl-chev">${ico("chevR")}</span></div>
  </div>`;
}

function listView(list) {
  const head = html`<div class="dl-head">
    <div>${sortHead("name", t("device.name"))}</div><div class="hide-s">${sortHead("type", t("device.type"))}</div>
    <div>${sortHead("ip", t("device.ip"))}</div><div class="hide-s">${sortHead("seen", t("device.status"))}</div><div></div></div>`;
  let body;
  if (st.sort === "status" && st.dir > 0) {
    const onl = list.filter((d) => d.online), off = list.filter((d) => !d.online);
    body = html`${onl.length ? html`<div class="dl-group"><span class="live"><i></i></span>${t("devices.f_online")}<b>${onl.length}</b></div>${onl.map(row)}` : ""}
      ${off.length ? html`<div class="dl-group"><span class="status-dot off"></span>${t("devices.f_offline")}<b>${off.length}</b></div>${off.map(row)}` : ""}`;
  } else body = list.map(row);
  return html`<div class="card dl">${head}<div class="dl-body">${body}</div></div>`;
}

function card(d) {
  return html`<div class="dc ${d.online ? "" : "is-off"}" data-id="${d.id}" tabindex="0" style="--c:${color(d)}">
    <div class="dc-top">${avatarWithStatus(d, "lg")}${favBtn(d)}</div>
    <div class="dc-name">${d.display_name}</div>
    <div class="dc-sub">${deviceSub(d)}</div>
    <div class="dc-chips"><span class="ip-pill mono">${d.ip}</span>${typePill(d)}</div>
    <div class="dc-foot">${seen(d)}<span class="dc-badges">${deviceBadges(d, { compact: true })}</span></div>
  </div>`;
}

const gridView = (list) => html`<div class="dc-grid">${list.map(card)}</div>`;

function paint() {
  if (!root) return;
  const c = counts(), list = filtered();
  const types = [...new Set(S.devices.map((d) => d.type || "unknown"))].sort((a, b) => t(`types.${a}`).localeCompare(t(`types.${b}`)));
  root.innerHTML = html`
    <div class="toolbar">
      <div class="row wrap" style="gap:6px">${["all", "online", "offline", "untrusted", "new", "blocked"].filter((f) => f !== "blocked" || c.blocked).map((f) =>
        html`<button class="chip ${st.filter === f ? "on" : ""}" data-filter="${f}">${t(`devices.f_${f}`)} <span class="n">${c[f]}</span></button>`)}
        ${st.type ? html`<button class="chip type-active" data-cleartype title="${t("devices.all_types")}">${raw(avatar(st.type, "xs"))}${t(`types.${st.type}`)} ${ico("x")}</button>` : ""}</div>
      <div class="grow"></div>
      <select class="input ${st.type ? "is-set" : ""}" id="type-f" style="width:auto;height:34px"><option value="">${t("devices.all_types")}</option>
        ${types.map((x) => html`<option value="${x}" ${st.type === x ? "selected" : ""}>${t(`types.${x}`)}</option>`)}</select>
      <div class="seg"><button class="${st.view === "list" ? "on" : ""}" data-view="list" aria-label="list">${ico("list")}</button><button class="${st.view === "grid" ? "on" : ""}" data-view="grid" aria-label="grid">${ico("grid")}</button></div>
      <button class="btn icon sm" id="more" aria-label="${t("common.more")}">${ico("more")}</button>
    </div>
    ${st.q ? html`<div class="faint" style="margin:-6px 0 12px">${t("devices.results", { count: list.length, q: st.q })}</div>` : ""}
    ${list.length ? (st.view === "grid" ? gridView(list) : listView(list)) :
      S.devices.length ? html`<div class="card">${emptyState("search", t("devices.none_match"), t("devices.none_match_hint"))}</div>` :
        html`<div class="card">${emptyState("radar", t("dash.no_devices"), t("dash.scan_hint"), html`<button class="btn primary" data-scan>${ico("radar")} ${t("scan.button")}</button>`)}</div>`}`;
}

async function toggleFav(id, btn) {
  const d = S.devices.find((x) => x.id === id);
  if (!d) return;
  d.favorite = !d.favorite;
  btn.classList.toggle("on", d.favorite);
  try { upsertDevice(await api(`/devices/${encodeURIComponent(id)}`, { method: "PATCH", body: { favorite: d.favorite } })); }
  catch (e) { d.favorite = !d.favorite; btn.classList.toggle("on", d.favorite); showError(e); }
}

function bind() {
  root.onclick = async (e) => {
    const fav = e.target.closest("[data-fav]"); if (fav) { e.stopPropagation(); return toggleFav(fav.dataset.fav, fav); }
    const f = e.target.closest("[data-filter]"); if (f) { st.filter = f.dataset.filter; return paint(); }
    if (e.target.closest("[data-cleartype]")) { st.type = ""; return paint(); }
    const v = e.target.closest("[data-view]"); if (v) { st.view = v.dataset.view; try { localStorage.setItem("ns-view", st.view); } catch { /* */ } return paint(); }
    const s = e.target.closest("[data-sort]"); if (s) { if (st.sort === s.dataset.sort) st.dir *= -1; else { st.sort = s.dataset.sort; st.dir = 1; } return paint(); }
    const item = e.target.closest("[data-id]"); if (item) return openDevice(item.dataset.id, order());
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
  root.onkeydown = (e) => {
    const item = e.target.closest?.("[data-id]");
    if (item && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openDevice(item.dataset.id, order()); }
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

/** ids in the order currently shown (used by the detail panel for previous / next). */
export const order = () => filtered().map((d) => d.id);

function render(el, arg, params) {
  root = el;
  st.q = $("#gsearch")?.value || "";
  if (params?.has("type")) { st.type = params.get("type"); st.filter = "all"; }
  else if (params?.has("new")) { st.filter = "new"; st.type = ""; }
  else if (!arg) { st.type = ""; st.filter = "all"; }
  paint(); bind();
  offSearch?.(); offSearch = on("search", (q) => { st.q = q || ""; paint(); });
}

let raf = false;
function onEvent(type) {
  if (!root || !["devices", "device", "resync"].includes(type) || raf) return;
  raf = true;
  requestAnimationFrame(() => { raf = false; if (root && document.body.contains(root)) { const sc = $("#content").scrollTop; paint(); $("#content").scrollTop = sc; } });
}

export default { render, onEvent, order, destroy() { root = null; offSearch?.(); offSearch = null; } };
