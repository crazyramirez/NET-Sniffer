import { api } from "../api.js";
import { lineChart, ring, sparkline } from "../charts.js";
import { deviceAvatar, deviceSub, emptyState, EVENT_ICON, eventClass, eventText, showError } from "../common.js";
import { fmt, t } from "../i18n.js";
import { avatar, TYPE_COLORS } from "../icons.js";
import { startScan } from "../main.js";
import { S } from "../store.js";
import { $, $$, html, ico, raw } from "../ui.js";
import { openDevice } from "./device.js";

let root, lat = [], events = [], celebrating = false, deferred = false, countUpNext = false;

// ------------------------------------------------------------------ scan experience
const PHASES = ["network", "discover", "identify", "merge"];
function hash(str) { let h = 2166136261; for (const c of str) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
function blipPos(d) {
  const h = hash(d.id), angle = (h % 360) * Math.PI / 180, r = 18 + ((h >>> 9) % 26);  // radius 18–43 % of the radar
  return { x: 50 + r * Math.cos(angle), y: 50 + r * Math.sin(angle) };
}
function scanTargets() {
  return [...S.devices].sort((a, b) => (b.online - a.online) || hash(a.id) - hash(b.id));
}
function revealed() {
  const sc = S.scan || {}, known = S.devices.filter((d) => d.online).length;
  if (sc.found) return sc.found;
  return Math.round(known * Math.min(1, (sc.progress || 0) / 45));  // before the count is known: grow with progress
}

function scanHero() {
  const sc = S.scan || {}, n = S.network || {}, pct = Math.max(2, sc.progress || 0);
  const idx = Math.max(0, PHASES.indexOf(sc.phase));
  const blips = scanTargets().slice(0, 48);
  const shown = revealed();
  return html`<div class="card hero scan-hero" id="scan-hero">
    <div class="radar-xl" id="radar">
      <svg class="radar-grid" viewBox="0 0 200 200" aria-hidden="true">
        <circle cx="100" cy="100" r="34"/><circle cx="100" cy="100" r="60"/><circle cx="100" cy="100" r="86"/>
        <path d="M100 8v184M8 100h184"/></svg>
      <div class="radar-sweep"></div>
      <i class="radar-pulse"></i><i class="radar-pulse d2"></i><i class="radar-pulse d3"></i>
      <svg class="radar-progress" viewBox="0 0 200 200" aria-hidden="true">
        <circle cx="100" cy="100" r="96" pathLength="100"/>
        <circle class="bar" id="radar-bar" cx="100" cy="100" r="96" pathLength="100" style="stroke-dashoffset:${100 - pct}"/></svg>
      <div class="blips" id="blips">${blips.map((d, i) => {
        const p = blipPos(d);
        return html`<i class="blip ${i < shown ? "on" : ""}" style="left:${p.x}%;top:${p.y}%;--c:${TYPE_COLORS[d.type] || TYPE_COLORS.unknown}"></i>`;
      })}</div>
      <div class="radar-core"><b class="num" id="scan-count">${shown}</b><span>${t("scan.devices")}</span></div>
    </div>
    <div style="min-width:0;position:relative;z-index:1">
      <div class="row" style="gap:8px;margin-bottom:6px"><span class="badge accent"><span class="spinner" style="width:10px;height:10px"></span>${t("scan.live")}</span></div>
      <h2>${t("scan.title")}</h2>
      <div class="muted">${n.wifi?.ssid ? `${n.wifi.ssid} · ` : ""}${n.cidr || ""}</div>
      <ol class="scan-steps" id="scan-steps">${PHASES.map((p, i) => html`<li class="${i < idx ? "done" : i === idx ? "now" : ""}">
        <span class="st-ico">${i < idx ? ico("check") : html`<i></i>`}</span>${t(`scan.phase_${p}`)}</li>`)}</ol>
      <div class="row" style="gap:12px;margin-top:16px"><div class="progress" style="flex:1"><i id="scan-bar" style="width:${pct}%"></i></div>
        <b class="num" id="scan-pct" style="min-width:42px;text-align:right">${pct}%</b></div>
    </div></div>`;
}

let shownCount = 0;
function updateScan() {
  const sc = S.scan || {}, pct = Math.max(2, sc.progress || 0), idx = Math.max(0, PHASES.indexOf(sc.phase));
  const bar = $("#radar-bar"); if (bar) bar.style.strokeDashoffset = String(100 - pct);
  const lin = $("#scan-bar"); if (lin) lin.style.width = pct + "%";
  const pc = $("#scan-pct"); if (pc) pc.textContent = pct + "%";
  $$(".scan-steps li").forEach((li, i) => {
    const state = i < idx ? "done" : i === idx ? "now" : "";
    if (li.className !== state) {
      li.className = state;
      li.querySelector(".st-ico").innerHTML = i < idx ? ico("check").s : "<i></i>";
    }
  });
  const target = revealed();
  $$("#blips .blip").forEach((b, i) => b.classList.toggle("on", i < target));
  const cnt = $("#scan-count");
  if (cnt && target !== shownCount) { countUp(cnt, shownCount, target, 500); shownCount = target; }
}

function countUp(el, from, to, ms = 700) {
  const t0 = performance.now();
  const step = (now) => {
    const k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 3);
    el.textContent = fmt.num(Math.round(from + (to - from) * e));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function celebrate() {
  const radar = $("#radar");
  celebrating = true;
  if (radar) {
    updateScan();
    radar.classList.add("done");
    const bar = $("#radar-bar"); if (bar) bar.style.strokeDashoffset = "0";
  }
  setTimeout(() => {
    celebrating = false; countUpNext = true; shownCount = 0;
    if (root && document.body.contains(root)) paint();
  }, radar ? 1100 : 0);
}

function health() {
  if (S.audit_last?.score !== undefined) return { score: S.audit_last.score, label: t("dash.security_score"), audited: true };
  let s = 100;
  if (S.monitor.status === "offline") s -= 30; else if (S.monitor.status === "degraded") s -= 10;
  const auth = (S.network.wifi?.auth || "").toUpperCase();
  if (auth === "OPEN" || auth.startsWith("WEP")) s -= 30; else if (auth.startsWith("WPA2")) s -= 4; else if (auth === "WPA") s -= 15;
  if (S.network.upnp_igd) s -= 6;
  const untrusted = S.devices.filter((d) => d.online && !d.trusted && !d.is_self).length;
  s -= Math.min(15, untrusted * 2);
  return { score: Math.max(0, s), label: t("dash.health"), audited: false };
}

function statusInfo() {
  const st = S.monitor.status || "unknown";
  return { st, cls: st === "online" ? "ok" : st === "degraded" ? "warn" : st === "offline" ? "danger" : "", dot: st === "online" ? "on" : st === "degraded" ? "warn" : st === "offline" ? "bad" : "off" };
}

function heroCard() {
  if (S.scan?.running || celebrating) return scanHero();
  const n = S.network, h = health(), wifi = n.wifi || {};
  const scanning = false;
  const sig = wifi.signal ?? null;
  return html`<div class="card hero">
    <div class="ring-wrap" id="ring">${raw(ring(h.score))}${scanning ? html`<div class="radar"></div>` : ""}
      <div class="ring-label"><b class="num">${h.score}</b><span>${h.label}</span></div></div>
    <div style="min-width:0;position:relative;z-index:1">
      <div class="row wrap" style="gap:8px;margin-bottom:6px">
        <span class="badge ${statusInfo().cls}"><span class="status-dot ${statusInfo().dot}"></span>${t(`monitor.status.${statusInfo().st}`)}</span>
        ${wifi.auth ? html`<span class="badge ${/WPA3/.test(wifi.auth) ? "ok" : /WPA2/.test(wifi.auth) ? "info" : "danger"}">${ico("lock")} ${wifi.auth}</span>` : ""}
        ${n.upnp_igd ? html`<span class="badge warn">UPnP</span>` : ""}
      </div>
      <h2>${wifi.ssid || (n.connection === "ethernet" ? t("network.ethernet") : t("network.your_network"))}</h2>
      <div class="muted">${n.router_vendor || n.router_model ? `${n.router_vendor || ""} ${n.router_model || ""} · ` : ""}${n.cidr || ""}</div>
      <div class="meta">
        <div><div class="l">${t("network.public_ip")}</div><div class="v mono">${n.public?.ip || "—"}</div></div>
        <div><div class="l">${t("network.isp")}</div><div class="v" title="${n.public?.isp || ""}">${n.public?.isp || "—"}</div></div>
        <div><div class="l">${t("network.gateway")}</div><div class="v mono">${n.gateway || "—"}</div></div>
        <div><div class="l">${t("network.local_ip")}</div><div class="v mono">${n.ip || "—"}</div></div>
        <div><div class="l">${t("network.signal")}</div><div class="v">${sig !== null ? `${sig}%${wifi.rssi ? ` · ${wifi.rssi} dBm` : ""}` : n.connection === "ethernet" ? t("network.wired") : "—"}</div></div>
        <div><div class="l">${t("network.band")}</div><div class="v">${wifi.band ? `${wifi.band}${wifi.channel ? ` · ch ${wifi.channel}` : ""}` : "—"}</div></div>
      </div>
      ${h.audited ? "" : html`<div class="row wrap" style="margin-top:16px">
        <a class="btn sm" href="#/security">${ico("shieldCheck")} ${t("dash.run_audit")}</a>
        <span class="faint" style="font-size:12.5px">${t("dash.health_hint")}</span></div>`}
    </div></div>`;
}

function kpis() {
  const on = S.devices.filter((d) => d.online);
  const day = Date.now() / 1000 - 86400;
  const fresh = S.devices.filter((d) => d.first_seen > day && !d.is_self).length;
  const untrusted = on.filter((d) => !d.trusted && !d.is_self).length;
  const sp = S.speed_last;
  return html`<div class="grid g-4">
    <a class="card kpi" href="#/devices" style="color:inherit;text-decoration:none"><div class="k-top"><span class="k-ico">${ico("devices")}</span>${t("dash.devices_online")}</div>
      <div class="k-val num" id="k-online">${on.length}<small>/ ${S.devices.length}</small></div>
      <div class="k-foot">${S.scan?.last ? t("dash.last_scan", { ago: fmt.ago(S.scan.last) }) : t("dash.never_scanned")}</div></a>
    <a class="card kpi" href="#/devices?new" style="color:inherit;text-decoration:none"><div class="k-top"><span class="k-ico ok">${ico("radar")}</span>${t("dash.new_24h")}</div>
      <div class="k-val num">${fresh}</div><div class="k-foot">${t("dash.new_hint")}</div></a>
    <a class="card kpi" href="#/devices" style="color:inherit;text-decoration:none"><div class="k-top"><span class="k-ico ${untrusted ? "warn" : "ok"}">${ico(untrusted ? "shieldAlert" : "shieldCheck")}</span>${t("dash.untrusted")}</div>
      <div class="k-val num">${untrusted}</div><div class="k-foot">${untrusted ? t("dash.untrusted_hint") : t("dash.all_trusted")}</div></a>
    <a class="card kpi" href="#/speed" style="color:inherit;text-decoration:none"><div class="k-top"><span class="k-ico info">${ico("gauge")}</span>${t("dash.last_speed")}</div>
      <div class="k-val num">${sp ? fmt.mbps(sp.download) : "—"}<small>Mbps</small></div>
      <div class="k-foot">${sp ? html`${ico("up")} ${fmt.mbps(sp.upload)} Mbps · ${fmt.num(sp.ping)} ms` : t("dash.run_speed")}</div></a>
  </div>`;
}

function internetCard() {
  const m = S.monitor, si = statusInfo();
  return html`<div class="card"><div class="card-h"><h3>${t("dash.internet")}</h3><span class="badge ${si.cls}"><span class="status-dot ${si.dot}"></span>${t(`monitor.status.${si.st}`)}</span>
    <div class="right"><a class="btn ghost sm" href="#/monitor">${t("common.details")} ${ico("chevR")}</a></div></div>
    <div class="card-b"><div class="row" style="gap:26px;margin-bottom:10px">
      <div><div class="faint" style="font-size:12px;font-weight:600">${t("monitor.latency")}</div><div style="font-size:24px;font-weight:750" class="num" id="d-lat">${m.latency ? fmt.num(m.latency, 0) : "—"}<small class="faint" style="font-size:13px"> ms</small></div></div>
      <div><div class="faint" style="font-size:12px;font-weight:600">${t("monitor.loss")}</div><div style="font-size:24px;font-weight:750" class="num" id="d-loss">${fmt.pct(m.loss ?? 0)}</div></div>
      <div><div class="faint" style="font-size:12px;font-weight:600">${t("monitor.since")}</div><div style="font-size:15px;font-weight:650;margin-top:6px">${m.since ? fmt.ago(m.since) : "—"}</div></div>
    </div><div id="d-latchart" style="height:70px">${raw(sparkline(lat.map((p) => p.y), { color: "var(--accent)", h: 70 }))}</div></div></div>`;
}

function bwCard() {
  return html`<div class="card"><div class="card-h"><h3>${t("dash.throughput")}</h3><span class="sub">${S.network.hostname || ""}</span>
    <div class="right legend"><span><i style="background:var(--accent-2)"></i>${ico("down")} <b class="num" id="bw-rx">${fmt.mbps(S.bandwidth.rx || 0)}</b> Mbps</span>
    <span><i style="background:var(--accent)"></i>${ico("up")} <b class="num" id="bw-tx">${fmt.mbps(S.bandwidth.tx || 0)}</b> Mbps</span></div></div>
    <div class="card-b"><div id="bw-chart" style="min-height:170px"></div></div></div>`;
}

function typesCard() {
  const counts = {};
  S.devices.filter((d) => d.online).forEach((d) => (counts[d.type || "unknown"] = (counts[d.type || "unknown"] || 0) + 1));
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  return html`<div class="card"><div class="card-h"><h3>${t("dash.by_type")}</h3></div><div class="card-b">
    ${entries.length ? html`<div class="type-chips">${entries.map(([k, v]) => html`<a class="type-chip" href="#/devices?type=${k}" data-type="${k}" style="color:inherit;text-decoration:none">${raw(avatar(k))}${t(`types.${k}`)} <b>${v}</b></a>`)}</div>`
      : html`<div class="faint">${t("dash.no_devices")}</div>`}</div></div>`;
}

function activityCard() {
  const list = events.slice(0, 8);
  return html`<div class="card"><div class="card-h"><h3>${t("dash.activity")}</h3><div class="right"><a class="btn ghost sm" href="#/alerts">${t("common.see_all")} ${ico("chevR")}</a></div></div>
    <div class="card-b" style="padding-top:6px">${list.length ? html`<div class="list">${list.map((ev) => {
      const { title, text } = eventText(ev);
      return html`<div class="li ${ev.device_id ? "click" : ""}" data-dev="${ev.device_id || ""}"><span class="ev-ico ${eventClass(ev)}">${ico(EVENT_ICON[ev.kind] || "info")}</span>
        <div class="li-main"><div class="li-t">${title}</div><div class="li-s">${text}</div></div><span class="faint" style="font-size:12px;white-space:nowrap">${fmt.ago(ev.ts)}</span></div>`;
    })}</div>` : emptyState("history", t("dash.no_activity"), t("dash.no_activity_hint"))}</div></div>`;
}

function recentDevices() {
  const list = [...S.devices].filter((d) => d.online).sort((a, b) => (b.first_seen || 0) - (a.first_seen || 0)).slice(0, 6);
  return html`<div class="card"><div class="card-h"><h3>${t("dash.recent_devices")}</h3><div class="right"><a class="btn ghost sm" href="#/devices">${t("common.see_all")} ${ico("chevR")}</a></div></div>
    <div class="card-b" style="padding-top:6px">${list.length ? html`<div class="list">${list.map((d) => html`<div class="li click" data-dev="${d.id}">${deviceAvatar(d, "sm")}
      <div class="li-main"><div class="li-t">${d.display_name}</div><div class="li-s">${deviceSub(d)}</div></div><span class="mono faint" style="font-size:12px">${d.ip}</span></div>`)}</div>`
      : emptyState("radar", t("dash.no_devices"), t("dash.scan_hint"), html`<button class="btn primary" data-scan>${ico("radar")} ${t("scan.button")}</button>`)}</div></div>`;
}

function drawBw() {
  const el = $("#bw-chart"); if (!el) return;
  // always show a 90-second window, even right after start-up
  const now = Date.now() / 1000;
  const pts = [...S.bw];
  if (!pts.length || pts[0].ts > now - 89) pts.unshift({ ts: Math.min(now - 90, pts[0]?.ts ?? now), rx: 0, tx: 0 });
  if (pts.length < 2) pts.push({ ts: now, rx: 0, tx: 0 });
  lineChart(el, [
    { name: "↓", color: "var(--accent-2)", values: pts.map((p) => ({ x: p.ts, y: p.rx })) },
    { name: "↑", color: "var(--accent)", values: pts.map((p) => ({ x: p.ts, y: p.tx })) },
  ], { height: 170, yFmt: (v) => fmt.mbps(v), xFmt: (v) => fmt.time(v), unit: " Mbps" });
}

function render(el) {
  root = el;
  paint();
  Promise.all([api("/monitor?hours=1"), api("/events?limit=12")]).then(([m, ev]) => {
    lat = m.series.map((p) => ({ x: p.ts, y: p.latency }));
    events = ev.events.filter((x) => x.kind !== "device_first_seen");
    if (root === el && document.body.contains(el)) paint();
  }).catch(showError);
}

function paint() {
  const el = root;
  el.innerHTML = html`<div class="stack">
    <div class="grid g-dash">${heroCard()}${internetCard()}</div>
    ${kpis()}
    <div class="grid g-dash"><div class="stack">${bwCard()}${typesCard()}</div><div class="stack">${recentDevices()}</div></div>
    ${activityCard()}
  </div>`;
  drawBw();
  if (S.scan?.running) { shownCount = revealed(); }
  if (countUpNext) {  // after a scan: numbers roll up to their new values
    countUpNext = false;
    $$(".kpi .k-val").forEach((k) => {
      const node = k.firstChild, txt = (node?.textContent || "").trim(), to = /^\d+$/.test(txt) ? +txt : NaN;
      if (node && Number.isFinite(to) && to > 0) { const span = document.createElement("span"); node.replaceWith(span); countUp(span, 0, to, 800); }
    });
    el.querySelector(".hero")?.classList.add("hero-reveal");
  }
  el.onclick = (e) => {
    const dev = e.target.closest("[data-dev]");
    if (dev?.dataset.dev) { openDevice(dev.dataset.dev); return; }
    if (e.target.closest("[data-scan]")) startScan();
  };
}

function repaint() {
  if (!root || !document.body.contains(root)) return;
  const st = $("#content").scrollTop; paint(); $("#content").scrollTop = st;
}

let pending = false;
function onEvent(type, data) {
  if (!root || !document.body.contains(root)) return;
  if (type === "bandwidth") {
    const rx = $("#bw-rx"), tx = $("#bw-tx");
    if (rx) rx.textContent = fmt.mbps(data.rx); if (tx) tx.textContent = fmt.mbps(data.tx);
    drawBw(); return;
  }
  if (type === "monitor") {
    lat.push({ x: data.last, y: data.latency });
    if (lat.length > 240) lat.shift();
  }
  if (type === "event") { events.unshift(data); events = events.slice(0, 20); }
  if (type === "scan") {
    const radar = $("#radar");
    if (data.running && radar) return updateScan();          // update in place: animations keep running
    if (data.running && !radar) return repaint();            // scan just started → show the radar
    if (!data.running && radar && !celebrating) { celebrate(); return; }
    if (!data.running && deferred) { deferred = false; return repaint(); }
    return;
  }
  if (S.scan?.running || celebrating) { deferred = true; return; }  // don't interrupt the scan animation
  if (["devices", "device", "network", "monitor", "event", "resync", "theme"].includes(type) && !pending) {
    pending = true;
    requestAnimationFrame(() => { pending = false; repaint(); });
  }
}

export default { render, onEvent, destroy() { root = null; } };
