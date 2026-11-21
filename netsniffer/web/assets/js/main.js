// App shell: auth gate, i18n, theme, routing, realtime events.
import { api, connectWS, setUnauthorizedHandler } from "./api.js";
import { eventClass, eventText, EVENT_ICON, showError } from "./common.js";
import { detectLang, fmt, LANGS, setLang, t } from "./i18n.js";
import { icon } from "./icons.js";
import { S, emit, upsertDevice } from "./store.js";
import { $, $$, html, ico, openMenu, openModal, toast, loadingBtn, drawerOpen, closeDrawer } from "./ui.js";
import dashboard from "./views/dashboard.js";
import devices from "./views/devices.js";
import security from "./views/security.js";
import speed from "./views/speed.js";
import monitor from "./views/monitor.js";
import alerts from "./views/alerts.js";
import parental from "./views/parental.js";
import settings from "./views/settings.js";
import { renderLogin } from "./views/login.js";
import { openDevice } from "./views/device.js";

const VIEWS = { dashboard, devices, security, speed, monitor, alerts, parental, settings };
const NAV = [
  { group: "nav.g_overview", items: [["dashboard", "dashboard"]] },
  { group: "nav.g_network", items: [["devices", "devices"], ["monitor", "activity"], ["speed", "gauge"]] },
  { group: "nav.g_protection", items: [["security", "shield"], ["parental", "family"], ["alerts", "bell"]] },
];
let current = null, currentName = null;

// ------------------------------------------------------------------ theme
const media = matchMedia("(prefers-color-scheme: dark)");
export function applyTheme(pref = S.settings.theme || "system") {
  const dark = pref === "dark" || (pref === "system" && media.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  try { localStorage.setItem("ns-theme", pref); } catch { /* private mode */ }
}
media.addEventListener("change", () => applyTheme());

export async function saveSettings(patch) {
  const res = await api("/settings", { method: "PUT", body: patch });
  S.settings = res.settings; S.remote = res.remote;
  return res;
}

// ------------------------------------------------------------------ shell
function navLink([name, ic]) {
  const badge = name === "alerts" && S.unread ? html`<span class="badge count">${S.unread > 99 ? "99+" : S.unread}</span>` : "";
  return html`<a href="#/${name}" data-nav="${name}">${ico(ic)}<span>${t(`nav.${name}`)}</span>${badge}</a>`;
}

function renderShell() {
  $("#app").innerHTML = html`<div class="app">
    <aside class="sidebar">
      <div class="brand"><div class="brand-logo">${ico("logo")}</div><div><div class="brand-name">NET Sniffer</div><div class="brand-sub">${t("app.tagline")}</div></div></div>
      <nav class="nav" id="nav">${NAV.map((g) => html`<div class="nav-label">${t(g.group)}</div>${g.items.map(navLink)}`)}
        <div class="nav-label">${t("nav.g_system")}</div>${navLink(["settings", "settings"])}</nav>
      <div id="side-status">${sideStatus()}</div>
      <div class="sidebar-foot"><span>v${S.app.version}</span><span class="row" style="gap:6px"><span class="status-dot ${S.ws ? "on" : "warn"}" id="ws-dot"></span>${S.ws ? t("common.live") : t("common.connecting")}</span></div>
    </aside>
    <div class="main">
      <header class="topbar">
        <h1 id="page-title"></h1>
        <span class="net-pill" id="net-pill"></span>
        <div class="spacer"></div>
        <label class="search"><span class="sr-only" hidden>${t("common.search")}</span>${ico("search")}
          <input id="gsearch" type="search" placeholder="${t("devices.search")}" autocomplete="off"><kbd>Ctrl K</kbd></label>
        <button class="btn grad" id="scan-btn">${ico("radar")}<span class="hide-m">${t("scan.button")}</span></button>
        <button class="icon-btn hide-m" id="alerts-btn" aria-label="${t("nav.alerts")}">${ico("bell")}${S.unread ? html`<span class="dot">${S.unread > 9 ? "9+" : S.unread}</span>` : ""}</button>
        <button class="icon-btn" id="theme-btn" aria-label="${t("settings.theme")}">${ico(document.documentElement.dataset.theme === "dark" ? "moon" : "sun")}</button>
        <button class="icon-btn" id="lang-btn" aria-label="${t("settings.language")}">${ico("globe")}</button>
      </header>
      <main class="content" id="content"></main>
    </div>
    <nav class="mobile-nav">${[["dashboard", "dashboard"], ["devices", "devices"], ["security", "shield"], ["speed", "gauge"], ["settings", "settings"]]
      .map(([n, i]) => html`<a href="#/${n}" data-nav="${n}">${ico(i)}<span>${t(`nav.${n}`)}</span></a>`)}</nav>
  </div>`;
  renderNetPill(); renderScanBtn();
  $("#scan-btn").onclick = startScan;
  $("#alerts-btn").onclick = () => (location.hash = "#/alerts");
  $("#theme-btn").onclick = async () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(next); $("#theme-btn").innerHTML = icon(next === "dark" ? "moon" : "sun");
    try { await saveSettings({ theme: next }); } catch (e) { showError(e); }
    current?.onEvent?.("theme");
  };
  $("#lang-btn").onclick = (e) => openMenu(e.currentTarget, [
    { label: t("settings.lang_auto"), on: S.settings.language === "auto", action: () => changeLang("auto") }, { sep: true },
    ...Object.entries(LANGS).map(([k, v]) => ({ label: v, on: S.settings.language === k, action: () => changeLang(k) })),
  ]);
  const search = $("#gsearch");
  search.addEventListener("input", () => {
    if (currentName !== "devices") location.hash = "#/devices";
    emit("search", search.value);
  });
  search.addEventListener("keydown", (e) => { if (e.key === "Escape") { search.value = ""; emit("search", ""); search.blur(); } });
}

export async function changeLang(l) {
  try { await saveSettings({ language: l }); } catch (e) { showError(e); }
  await setLang(detectLang(l, S.app.os_language));
  rerender();
}

function sideStatus() {
  const m = S.monitor || {}, st = m.status || "unknown";
  const dot = { online: "on", degraded: "warn", offline: "bad" }[st] || "off";
  const on = (S.devices || []).filter((d) => d.online).length;
  return html`<a class="plan-card" href="#/monitor" style="display:block;color:inherit;text-decoration:none">
    <div class="row"><span class="status-dot ${dot} ${st === "online" ? "pulse" : ""}"></span><div class="title">${t("dash.internet")}</div>
      <span class="faint num" style="margin-left:auto;font-size:12px">${m.latency ? `${fmt.num(m.latency, 0)} ms` : ""}</span></div>
    <div class="sub">${t(`monitor.status.${st}`)} · ${on} ${t("nav.devices").toLowerCase()}</div></a>`;
}
function updateSideStatus() { const el = $("#side-status"); if (el) el.innerHTML = sideStatus(); }

function renderNetPill() {
  const n = S.network || {}, el = $("#net-pill");
  if (!el) return;
  const wifi = n.wifi?.ssid;
  el.innerHTML = html`${ico(wifi ? "wifi" : "ethernet")}<b style="color:var(--text)">${wifi || t("network.ethernet")}</b><span>·</span><span class="mono">${n.cidr || "—"}</span>`;
}

function renderScanBtn() {
  const b = $("#scan-btn"); if (!b) return;
  const sc = S.scan || {};
  if (sc.running) { b.disabled = true; b.innerHTML = html`<span class="spinner"></span><span class="hide-m">${t("scan.scanning")} ${sc.progress || 0}%</span>`; }
  else { b.disabled = false; b.innerHTML = html`${ico("radar")}<span class="hide-m">${t("scan.button")}</span>`; }
}

export async function startScan(deep = false) {
  try {
    const r = await api("/scan", { method: "POST", body: { deep: deep === true } });
    if (r.started) { S.scan = { ...S.scan, running: true, progress: 1 }; renderScanBtn(); emit("scan", S.scan); }
  } catch (e) { showError(e); }
}

function updateNav() {
  $$("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === currentName));
}

// ------------------------------------------------------------------ routing
function route() {
  if (drawerOpen() && !location.hash.startsWith("#/devices/")) closeDrawer();
  // "#/devices/<id>?type=camera" → name "devices", arg "<id>", params {type: "camera"}
  const [path, query = ""] = location.hash.split("?");
  const [, name = "dashboard", arg] = path.split("/");
  const params = new URLSearchParams(query);
  const view = VIEWS[name] || dashboard;
  const vname = VIEWS[name] ? name : "dashboard";
  if (vname !== currentName) { current?.destroy?.(); current = view; currentName = vname; }
  $("#page-title").textContent = t(`nav.${vname}`);
  document.title = `${t(`nav.${vname}`)} · NET Sniffer`;
  updateNav();
  const root = $("#content");
  root.innerHTML = `<div class="page" id="page"></div>`;
  view.render($("#page"), arg, params);
  if (vname === "devices" && arg) openDevice(decodeURIComponent(arg), devices.order?.());
}

export function rerender() {
  const scroll = $("#content")?.scrollTop || 0;
  renderShell(); route();
  const c = $("#content"); if (c) c.scrollTop = scroll;
}
window.addEventListener("ns:rerender", () => refreshState().then(rerender));

async function refreshState() {
  Object.assign(S, await api("/state"));
}

// ------------------------------------------------------------------ realtime
function onWS(type, data) {
  switch (type) {
    case "scan": {
      const finished = S.scan?.running && !data.running && data.kind === "full";
      S.scan = data; renderScanBtn();
      if (finished) toast({ kind: "ok", iconName: "radar", title: t("scan.done_title"), text: t("scan.done_text", { count: data.found || 0, s: fmt.num(data.duration || 0, 1) }) });
      break;
    }
    case "scan_error": toast({ kind: "error", title: t("scan.failed"), text: t(`errors.${data.error}`) }); break;
    case "devices": S.devices = data; updateSideStatus(); break;
    case "device": upsertDevice(data); break;
    case "network": S.network = data; renderNetPill(); break;
    case "monitor": S.monitor = data; updateSideStatus(); break;
    case "bandwidth": S.bandwidth = data; S.bw.push(data); if (S.bw.length > 90) S.bw.shift(); break;
    case "settings": S.settings = data.settings; S.remote = data.remote; break;
    case "update":
      S.update = data;
      if (data.status === "ready" && !S._updToast) {
        S._updToast = true;
        toast({ kind: "ok", iconName: "download", title: t("update.ready_title", { v: data.latest }), text: t("update.ready_text"), timeout: 0,
          action: { label: t("update.restart"), run: () => api("/update/apply", { method: "POST" }).catch(showError) } });
      }
      break;
    case "unread": S.unread = data; updateBell(); break;
    case "event": {
      if (data.severity !== "debug" && data.id) S.unread += ["warning", "critical"].includes(data.severity) ? 1 : 0;
      updateBell();
      if (["warning", "critical"].includes(data.severity) || ["internet_up"].includes(data.kind)) {
        const { title, text } = eventText(data);
        toast({ kind: eventClass(data) === "ok" ? "ok" : eventClass(data), iconName: EVENT_ICON[data.kind], title, text });
      }
      break;
    }
    case "blocking": S.blocking = data; break;
  }
  current?.onEvent?.(type, data);
  emit(type, data);
}

function updateBell() {
  const b = $("#alerts-btn");
  if (b) b.innerHTML = icon("bell") + (S.unread ? `<span class="dot">${S.unread > 9 ? "9+" : S.unread}</span>` : "");
  const nav = $('#nav [data-nav="alerts"]');
  if (nav) { nav.outerHTML = navLink(["alerts", "bell"]).s; updateNav(); }
}

// ------------------------------------------------------------------ onboarding
function onboarding() {
  const feats = [["radar", "onb.f1"], ["shieldCheck", "onb.f2"], ["gauge", "onb.f3"], ["bell", "onb.f4"]];
  openModal({
    dismissible: false, wide: true,
    body: html`<div class="onb-hero"><div class="brand-logo">${ico("logo")}</div><h2>${t("onb.title")}</h2><p class="muted">${t("onb.subtitle")}</p></div>
      <div class="onb-feats">${feats.map(([i, k]) => html`<div class="onb-feat">${ico(i)}<div><b>${t(k + "_t")}</b><div class="faint">${t(k + "_d")}</div></div></div>`)}</div>
      <div class="sep"></div>
      <div class="banner accent"><div class="b-ico">${ico("shield")}</div><div class="b-txt"><div class="b-t">${t("onb.legal_t")}</div><div class="b-d">${t("onb.legal_d")}</div></div></div>
      <label class="check" style="margin-top:14px"><input type="checkbox" id="onb-ok"> <span>${t("onb.accept")}</span></label>`,
    footer: html`<button class="btn grad lg" id="onb-go" disabled>${ico("radar")} ${t("onb.start")}</button>`,
    onMount: (el, close) => {
      const cb = el.querySelector("#onb-ok"), go = el.querySelector("#onb-go");
      cb.onchange = () => (go.disabled = !cb.checked);
      go.onclick = async () => { await saveSettings({ onboarded: true }).catch(showError); close(); startScan(); };
    },
  });
}

// ------------------------------------------------------------------ boot
async function boot() {
  applyTheme((() => { try { return localStorage.getItem("ns-theme") || "system"; } catch { return "system"; } })());
  setUnauthorizedHandler(() => location.reload());
  let status;
  try { status = await api("/auth/status"); } catch { status = { authenticated: false }; }
  if (!status.authenticated) {
    await setLang(detectLang("auto", "en"));
    renderLogin(status);
    return;
  }
  await refreshState();
  applyTheme(S.settings.theme);
  await setLang(detectLang(S.settings.language, S.app.os_language));
  rerender();
  window.addEventListener("hashchange", () => route());
  connectWS(onWS, (online) => {
    S.ws = online;
    const dot = $("#ws-dot"); if (dot) { dot.className = `status-dot ${online ? "on" : "warn"}`; dot.parentElement.lastChild.textContent = online ? t("common.live") : t("common.connecting"); }
    if (online) refreshState().then(() => current?.onEvent?.("resync")).catch(() => {});
  });
  document.addEventListener("click", (e) => {
  });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#gsearch")?.focus(); }
  });
  if (!S.settings.onboarded) onboarding();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
}

boot().catch((e) => {
  console.error(e);
  document.getElementById("app").innerHTML = `<div class="login"><div class="card" style="text-align:center"><h3>NET Sniffer</h3><p class="muted">${String(e.message || e)}</p><button class="btn primary" onclick="location.reload()">Reload</button></div></div>`;
});
export { fmt, loadingBtn };
