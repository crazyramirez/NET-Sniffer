import { api } from "../api.js";
import { barChart } from "../charts.js";
import { emptyState, showError } from "../common.js";
import { fmt, t } from "../i18n.js";
import { S } from "../store.js";
import { $, html, ico, raw } from "../ui.js";

let root, hist = [], run = null, shown = 0, target = 0, raf = 0;
const TICKS = [0, 5, 10, 25, 50, 100, 250, 500, 1000];
const CX = 150, CY = 150, R = 118, A0 = 135, SWEEP = 270, LEN = (R * SWEEP * Math.PI) / 180;

const frac = (v) => {
  if (v <= 0) return 0;
  if (v >= TICKS.at(-1)) return 1;
  for (let i = 1; i < TICKS.length; i++) if (v <= TICKS[i]) return (i - 1 + (v - TICKS[i - 1]) / (TICKS[i] - TICKS[i - 1])) / (TICKS.length - 1);
  return 1;
};
const pt = (deg, r = R) => [CX + r * Math.cos((deg * Math.PI) / 180), CY + r * Math.sin((deg * Math.PI) / 180)];
function arcPath() {
  const [x0, y0] = pt(A0), [x1, y1] = pt(A0 + SWEEP);
  return `M${x0},${y0} A${R},${R} 0 1 1 ${x1},${y1}`;
}

function gaugeSvg() {
  const labels = TICKS.map((v, i) => {
    const a = A0 + (SWEEP * i) / (TICKS.length - 1), [x, y] = pt(a, R - 30);
    return `<text x="${x}" y="${y + 4}" text-anchor="middle" font-size="11" font-weight="600" fill="var(--text-3)">${v}</text>`;
  }).join("");
  const phase = run?.phase;
  const col = phase === "upload" ? "url(#gUp)" : "url(#gDown)";
  return `<svg viewBox="0 0 300 234"><defs>
    <linearGradient id="gDown" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#06B6D4"/><stop offset="1" stop-color="#6366F1"/></linearGradient>
    <linearGradient id="gUp" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#8B5CF6"/><stop offset="1" stop-color="#EC4899"/></linearGradient>
    <filter id="glow"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
    <path d="${arcPath()}" fill="none" stroke="var(--panel-3)" stroke-width="16" stroke-linecap="round"/>
    <path id="g-arc" d="${arcPath()}" fill="none" stroke="${col}" stroke-width="16" stroke-linecap="round" stroke-dasharray="${LEN}" stroke-dashoffset="${LEN}" filter="url(#glow)"/>
    ${labels}</svg>`;
}

function tick() {
  shown += (target - shown) * 0.12;
  if (Math.abs(target - shown) < 0.05) shown = target;
  const arc = document.getElementById("g-arc"), v = document.getElementById("g-num");
  if (arc) arc.setAttribute("stroke-dashoffset", String(LEN * (1 - frac(shown))));
  if (v && run && ["download", "upload"].includes(run.phase)) v.textContent = fmt.mbps(shown);
  raf = shown !== target ? requestAnimationFrame(tick) : 0;
}
function setTarget(v) { target = v; if (!raf) raf = requestAnimationFrame(tick); }

function metric(key, label, value, unit, iconName) {
  const active = run && run.phase === key;
  return html`<div class="card metric ${active ? "active" : ""}"><div class="m-l">${ico(iconName)}${label}</div>
    <div class="m-v num">${value ?? "—"}<small>${unit}</small></div></div>`;
}

function paint() {
  if (!root) return;
  const last = run?.result || (run ? null : hist[0]);
  const live = run && !run.result;
  const ph = run?.phase;
  const v = live ? { ping: run.r.ping, jitter: null, download: run.r.download, upload: run.r.upload }
    : { ping: last?.ping, jitter: last?.jitter, download: last?.download, upload: last?.upload };
  root.innerHTML = html`<div class="stack">
    <div class="card"><div class="speed-stage">
      <div class="gauge">${raw(gaugeSvg())}
        ${live ? html`<div class="g-val"><b id="g-num">${ph === "ping" || ph === "connect" ? (run.ping ? fmt.num(run.ping, 0) : "…") : fmt.mbps(shown)}</b>
          <span>${ph === "ping" || ph === "connect" ? "ms · " + t("speed.ping") : `Mbps · ${t(`speed.${ph}`)}`}</span></div>`
          : html`<button class="go" id="go">${t("speed.go")}</button>`}
      </div>
      <div class="row wrap" style="justify-content:center;gap:10px;margin:6px 0 16px;color:var(--text-2);font-size:13px">
        ${ico("globe")} <span>${last?.isp || S.network.public?.isp || t("network.isp")}</span><span class="faint">·</span>${ico("t_server")}<span>${last?.server || "Cloudflare"}</span>
        ${last?.ts && !live ? html`<span class="faint">· ${fmt.ago(last.ts)}</span>` : ""}
      </div></div></div>
    <div class="speed-metrics">
      ${metric("download", t("speed.download"), v.download != null ? fmt.mbps(v.download) : null, "Mbps", "down")}
      ${metric("upload", t("speed.upload"), v.upload != null ? fmt.mbps(v.upload) : null, "Mbps", "up")}
      ${metric("ping", t("speed.ping"), v.ping != null ? fmt.num(v.ping, 0) : null, "ms", "activity")}
      ${metric("jitter", t("speed.jitter"), v.jitter != null ? fmt.num(v.jitter, 1) : null, "ms", "zap")}
    </div>
    <div class="card"><div class="card-h"><h3>${t("speed.history")}</h3>
      <div class="right legend"><span><i style="background:#06B6D4"></i>${t("speed.download")}</span><span><i style="background:#A855F7"></i>${t("speed.upload")}</span></div></div>
      <div class="card-b">${hist.length ? html`<div id="hist-chart"></div>
        <div style="overflow-x:auto;margin-top:12px"><table class="table"><thead><tr><th>${t("speed.date")}</th><th>${t("speed.download")}</th><th>${t("speed.upload")}</th><th>${t("speed.ping")}</th><th class="hide-s">${t("speed.jitter")}</th><th class="hide-s">${t("network.isp")}</th></tr></thead>
        <tbody>${hist.slice(0, 15).map((h) => html`<tr style="cursor:default"><td>${fmt.date(h.ts)}</td><td class="num"><b>${fmt.mbps(h.download)}</b> Mbps</td><td class="num">${fmt.mbps(h.upload)} Mbps</td><td class="num">${fmt.num(h.ping, 0)} ms</td><td class="num hide-s">${fmt.num(h.jitter, 1)} ms</td><td class="hide-s faint">${h.isp || ""}</td></tr>`)}</tbody></table></div>`
        : emptyState("gauge", t("speed.no_history"), t("speed.no_history_d"))}</div></div>
  </div>`;
  const arc = document.getElementById("g-arc");
  if (arc) arc.setAttribute("stroke-dashoffset", String(LEN * (1 - frac(live ? shown : last?.download || 0))));
  if (!live && last) { shown = last.download || 0; }
  const hc = $("#hist-chart");
  if (hc) barChart(hc, hist.slice(0, 14).reverse().map((h) => ({ label: fmt.day(h.ts), values: [{ v: h.download, color: "#06B6D4" }, { v: h.upload, color: "#A855F7" }] })), { height: 180, yFmt: (x) => fmt.mbps(x) });
}

async function start() {
  try { await api("/speedtest", { method: "POST" }); run = { phase: "connect", r: {} }; shown = 0; target = 0; paint(); }
  catch (e) { showError(e); }
}

function render(el) {
  root = el; run = null;
  api("/speedtest/history").then((r) => {
    hist = r.history;
    if (r.running && r.last) run = { ...r.last, r: {} };
    paint();
  }).catch(showError);
  paint();
  el.onclick = (e) => { if (e.target.closest("#go")) start(); };
}

function onEvent(type, p) {
  if (type !== "speed" || !root) return;
  if (p.phase === "error") { run = null; showError({ key: p.error || "speedtest_failed" }); return paint(); }
  const prevPhase = run?.phase;
  run = { ...(run || { r: {} }), ...p, r: run?.r || {} };
  if (p.phase === "ping") run.r.ping = p.ping;
  if (p.phase === "download") { run.r.download = p.speed; setTarget(p.speed); }
  if (p.phase === "upload") { if (prevPhase === "download") { shown = 0; } run.r.upload = p.speed; setTarget(p.speed); }
  if (p.phase === "done") {
    hist.unshift(p.result); S.speed_last = p.result; run = null; setTarget(p.result.download); return paint();
  }
  if (prevPhase !== p.phase) paint();
  else {
    const n = document.getElementById("g-num");
    if (n && p.phase === "ping") n.textContent = p.ping ? fmt.num(p.ping, 0) : "…";
    const cards = root.querySelectorAll(".metric .m-v");
    if (p.phase === "download" && cards[0]) cards[0].innerHTML = `${fmt.mbps(p.speed)}<small>Mbps</small>`;
    if (p.phase === "upload" && cards[1]) cards[1].innerHTML = `${fmt.mbps(p.speed)}<small>Mbps</small>`;
    if (p.phase === "ping" && cards[2] && p.ping) cards[2].innerHTML = `${fmt.num(p.ping, 0)}<small>ms</small>`;
  }
}

export default { render, onEvent, destroy() { root = null; cancelAnimationFrame(raf); raf = 0; } };
