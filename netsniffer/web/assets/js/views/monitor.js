import { api } from "../api.js";
import { lineChart } from "../charts.js";
import { emptyState, showError } from "../common.js";
import { fmt, t } from "../i18n.js";
import { S } from "../store.js";
import { $, html, ico } from "../ui.js";

let root, data = null, hours = 24;

function statusHero() {
  const m = S.monitor || {}, st = m.status || "unknown";
  const cls = { online: "ok", degraded: "warn", offline: "danger" }[st] || "info";
  const ic = { online: "checkCircle", degraded: "alert", offline: "x" }[st] || "clock";
  return html`<div class="grid g-4">
    <div class="card kpi"><div class="k-top"><span class="k-ico ${cls}">${ico(ic)}</span>${t("monitor.connection")}</div>
      <div class="k-val" style="font-size:24px">${t(`monitor.status.${st}`)}</div><div class="k-foot">${t("monitor.since_ago", { ago: fmt.ago(m.since) })}</div></div>
    <div class="card kpi"><div class="k-top"><span class="k-ico info">${ico("activity")}</span>${t("monitor.latency")}</div>
      <div class="k-val num">${m.latency ? fmt.num(m.latency, 0) : "—"}<small>ms</small></div><div class="k-foot">${t("monitor.avg")} ${data?.latency_avg ? fmt.num(data.latency_avg, 0) + " ms" : "—"} · p95 ${data?.latency_p95 ? fmt.num(data.latency_p95, 0) + " ms" : "—"}</div></div>
    <div class="card kpi"><div class="k-top"><span class="k-ico ok">${ico("shieldCheck")}</span>${t("monitor.uptime")}</div>
      <div class="k-val num">${data?.uptime != null ? fmt.num(data.uptime, 2) : "—"}<small>%</small></div><div class="k-foot">${t("monitor.last_hours", { count: hours })}</div></div>
    <div class="card kpi"><div class="k-top"><span class="k-ico ${data?.outages?.length ? "danger" : "ok"}">${ico("globe")}</span>${t("monitor.outages")}</div>
      <div class="k-val num">${data?.outages?.length ?? "—"}</div><div class="k-foot">${m.gw_ok === false ? t("monitor.gw_down") : t("monitor.gw_ok")} · DNS ${m.dns_ok ? "✓" : "✗"}</div></div>
  </div>`;
}

function paint() {
  if (!root) return;
  root.innerHTML = html`<div class="stack">${statusHero()}
    <div class="card"><div class="card-h"><h3>${t("monitor.latency_chart")}</h3>
      <div class="right"><div class="seg">${[[1, "1h"], [24, "24h"], [168, "7d"], [720, "30d"]].map(([h, l]) =>
        html`<button class="${hours === h ? "on" : ""}" data-h="${h}">${l}</button>`)}</div></div></div>
      <div class="card-b"><div id="lat-chart" style="min-height:220px">${data ? "" : html`<div class="skeleton" style="height:220px"></div>`}</div></div></div>
    <div class="grid g-2" style="align-items:start">
      <div class="card"><div class="card-h"><h3>${t("monitor.outage_log")}</h3></div><div class="card-b">
        ${data?.outages?.length ? html`<div class="list">${data.outages.map((o) => html`<div class="li"><span class="ev-ico ${o.end ? "warning" : "critical"}">${ico(o.scope === "lan" ? "t_router" : "globe")}</span>
          <div class="li-main"><div class="li-t">${o.scope === "lan" ? t("monitor.lan_outage") : t("monitor.inet_outage")} · ${fmt.dur(o.duration)}</div>
          <div class="li-s">${fmt.date(o.start)}${o.end ? ` → ${fmt.time(o.end)}` : ` · ${t("monitor.ongoing")}`}</div></div></div>`)}</div>`
          : emptyState("checkCircle", t("monitor.no_outages"), t("monitor.no_outages_d"))}</div></div>
      <div class="card"><div class="card-h"><h3>${t("monitor.how_t")}</h3></div><div class="card-b muted" style="font-size:13.5px">
        <p style="margin-top:0">${t("monitor.how_d")}</p>
        <div class="kv-grid"><div>${t("monitor.targets")}</div><div class="mono">1.1.1.1 · 8.8.8.8 · 9.9.9.9</div>
          <div>${t("network.gateway")}</div><div class="mono">${S.network.gateway || "—"}</div>
          <div>${t("monitor.interval")}</div><div>${S.settings.monitor_interval_s || 15} s</div>
          <div>${t("monitor.samples")}</div><div class="num">${fmt.num(data?.samples || 0)}</div></div></div></div>
    </div></div>`;
  const el = $("#lat-chart");
  if (el && data) {
    const span = hours * 3600;
    lineChart(el, [
      { name: t("monitor.latency"), color: "var(--accent)", values: data.series.map((p) => ({ x: p.ts, y: p.latency })) },
      { name: t("monitor.loss"), color: "var(--danger)", fill: false, values: data.series.map((p) => ({ x: p.ts, y: p.loss ? p.loss : null })) },
    ], { height: 220, yFmt: (v) => fmt.num(v, 0), xFmt: (v, full) => (span > 86400 && !full ? fmt.day(v) : full ? fmt.date(v) : fmt.time(v)), unit: "" });
  }
}

async function load() {
  try { data = await api(`/monitor?hours=${hours}`); paint(); } catch (e) { showError(e); }
}

function render(el) {
  root = el; paint(); load();
  el.onclick = (e) => {
    const b = e.target.closest("[data-h]");
    if (b) {
      const h = +b.dataset.h;
      hours = h; data = null; paint(); load();
    }
  };
}
let last = 0;
function onEvent(type) {
  if (!root) return;
  if (type === "monitor" && Date.now() - last > 30000) { last = Date.now(); load(); }
}
export default { render, onEvent, destroy() { root = null; } };
