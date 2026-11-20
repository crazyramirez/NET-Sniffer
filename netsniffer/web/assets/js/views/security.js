import { api } from "../api.js";
import { ring } from "../charts.js";
import { emptyState, proLock, showError } from "../common.js";
import { fmt, has, t } from "../i18n.js";
import { S, can } from "../store.js";
import { html, ico, raw, loadingBtn } from "../ui.js";
import { openDevice } from "./device.js";

let root, progress = null, cams = null, camBusy = false;
const SEV = ["critical", "high", "medium", "low", "info"];
const SEV_COLOR = { critical: "var(--danger)", high: "#F97316", medium: "var(--warn)", low: "var(--info)", info: "var(--text-3)" };
const grade = (s) => (s >= 90 ? "A" : s >= 80 ? "B" : s >= 65 ? "C" : s >= 50 ? "D" : "F");

function fParams(f) {
  const p = { ...(f.params || {}) };
  return p;
}

function finding(f) {
  const p = fParams(f), base = `audit.f.${f.id}`;
  return html`<details class="finding ${f.severity}"><summary><span class="sev"></span>
    <div style="min-width:0;flex:1"><div class="f-t">${t(`${base}.title`, p)}</div><div class="f-s">${p.device ? `${p.device} · ${p.ip}${p.port ? `:${p.port}` : ""}` : t(`severity.${f.severity}`)}</div></div>
    <span class="badge sev-badge ${f.severity}">${t(`severity.${f.severity}`)}</span><span class="chev">${ico("chevR")}</span></summary>
    <div class="f-b"><div>${t(`${base}.desc`, p)}</div>${has(`${base}.fix`) ? html`<h5>${t("audit.how_to_fix")}</h5><div>${t(`${base}.fix`, p)}</div>` : ""}
    ${p.banner ? html`<h5>${t("audit.banner")}</h5><div class="mono" style="font-size:12px">${p.banner}</div>` : ""}
    ${f.device_id ? html`<div style="margin-top:12px"><button class="btn xs" data-dev="${f.device_id}">${ico("devices")} ${t("audit.view_device")}</button></div>` : ""}</div></details>`;
}

function scoreCard(rep) {
  const c = rep?.counts || {};
  const total = SEV.reduce((a, k) => a + (c[k] || 0), 0);
  return html`<div class="card hero" style="grid-template-columns:auto 1fr">
    <div class="ring-wrap">${raw(ring(rep ? rep.score : 0))}${progress ? html`<div class="radar"></div>` : ""}
      <div class="ring-label"><b class="num">${rep ? rep.score : "—"}</b><span>${rep ? `${t("security.grade")} ${grade(rep.score)}` : t("security.not_run")}</span></div></div>
    <div style="min-width:0;position:relative;z-index:1">
      <h2>${rep ? t(rep.score >= 80 ? "security.good" : rep.score >= 60 ? "security.fair" : "security.poor") : t("security.title")}</h2>
      <div class="muted">${rep ? t("security.summary", { count: total, devices: rep.devices, ago: fmt.ago(rep.ts) }) : t("security.intro")}</div>
      ${rep ? html`<div class="sev-bar" style="margin-top:16px">${SEV.filter((k) => c[k]).map((k) => html`<i style="flex:${c[k]};background:${SEV_COLOR[k]}"></i>`)}</div>
        <div class="row wrap" style="gap:14px;margin-top:10px;font-size:12.5px">${SEV.filter((k) => k !== "info").map((k) => html`<span class="row" style="gap:6px"><i style="width:9px;height:9px;border-radius:3px;background:${SEV_COLOR[k]};display:inline-block"></i>${t(`severity.${k}`)} <b>${c[k] || 0}</b></span>`)}</div>` : ""}
      <div class="row wrap" style="margin-top:18px">
        <button class="btn grad" id="run" ${progress ? "disabled" : ""}>${progress ? html`<span class="spinner"></span> ${t("security.running")} ${Math.round(progress.progress * 100)}%` : html`${ico("shieldCheck")} ${rep ? t("security.rerun") : t("security.run")}`}</button>
        ${rep && can("export") ? html`<a class="btn" href="/api/export/report.html">${ico("file")} ${t("security.report")}</a>` : ""}
      </div>
      ${progress ? html`<div class="progress" style="margin-top:14px"><i style="width:${Math.round(progress.progress * 100)}%"></i></div><div class="faint" style="font-size:12px;margin-top:6px">${progress.device ? t("security.checking", { name: progress.device }) : t(`security.phase_${progress.phase}`)}</div>` : ""}
    </div></div>`;
}

function camerasCard() {
  return html`<div class="card"><div class="card-h"><span class="ev-ico critical">${ico("t_camera")}</span><div><h3>${t("cams.title")}</h3><div class="sub">${t("cams.subtitle")}</div></div>
    <div class="right"><button class="btn sm" id="cams" ${camBusy ? "disabled" : ""}>${camBusy ? html`<span class="spinner"></span>` : ico("eye")} ${t("cams.run")}</button></div></div>
    <div class="card-b">${cams === null ? html`<div class="faint">${t("cams.hint")}</div>` : cams.cameras.length ? html`<div class="list">${cams.cameras.map((c) => html`<div class="li click" data-dev="${c.device_id}">
      <span class="ev-ico ${c.trusted ? "info" : "critical"}">${ico("t_camera")}</span><div class="li-main"><div class="li-t">${c.name}</div>
      <div class="li-s">${c.ip} · ${c.vendor || t("device.unknown_vendor")} · ${c.reasons.map((r) => t(`cams.reason_${r}`)).join(", ")}</div></div>
      <span class="badge ${c.confidence === "high" ? "danger" : "warn"}">${t(`cams.conf_${c.confidence}`)}</span>${c.trusted ? "" : html`<span class="badge warn">${t("device.untrusted")}</span>`}</div>`)}</div>
      <p class="faint" style="font-size:12.5px;margin-bottom:0">${t("cams.advice")}</p>`
      : html`<div class="banner accent"><div class="b-ico">${ico("checkCircle")}</div><div class="b-txt"><div class="b-t">${t("cams.none")}</div><div class="b-d">${t("cams.none_d", { count: cams.scanned })}</div></div></div>`}</div></div>`;
}

function paint() {
  if (!root) return;
  const rep = S.audit_last;
  const groups = rep ? SEV.map((k) => [k, rep.findings.filter((f) => f.severity === k)]).filter(([, l]) => l.length) : [];
  const body = html`<div class="stack">${scoreCard(rep)}
    <div class="grid g-dash" style="align-items:start">
      <div class="stack"><div class="card"><div class="card-h"><h3>${t("security.findings")}</h3>${rep ? html`<span class="sub">${rep.findings.length}</span>` : ""}</div><div class="card-b">
        ${rep ? (rep.findings.length ? groups.map(([, l]) => l.map(finding)) : emptyState("shieldCheck", t("security.no_findings"), t("security.no_findings_d")))
          : emptyState("shield", t("security.not_run"), t("security.intro_long"))}</div></div></div>
      <div class="stack">
        ${proLock("cameras", camerasCard(), { compact: true })}
        ${rep ? html`<div class="card"><div class="card-h"><h3>${t("security.passed")}</h3></div><div class="card-b">${rep.passed.length ? rep.passed.map((p) => html`<div class="pass">${ico("checkCircle")}${t(`audit.pass.${p}`)}</div>`) : html`<div class="faint">—</div>`}</div></div>` : ""}
        <div class="card pad"><div class="row" style="align-items:flex-start;gap:12px"><span class="ev-ico info">${ico("info")}</span><div><b>${t("security.ethics_t")}</b><div class="faint" style="font-size:13px;margin-top:2px">${t("security.ethics_d")}</div></div></div></div>
      </div></div></div>`;
  root.innerHTML = proLock("audit", body).s;
}

function render(el) {
  root = el;
  api("/audit").then((r) => { if (r.report) S.audit_last = r.report; if (r.running && !progress) progress = { phase: "ports", progress: 0.1 }; paint(); }).catch(() => {});
  paint();
  el.onclick = async (e) => {
    const dev = e.target.closest("[data-dev]"); if (dev) return openDevice(dev.dataset.dev);
    if (e.target.closest("#run")) {
      try { await api("/audit", { method: "POST" }); progress = { phase: "network", progress: 0.02 }; paint(); } catch (er) { showError(er); }
    }
    const cb = e.target.closest("#cams");
    if (cb) {
      camBusy = true; paint();
      try { cams = await api("/cameras", { method: "POST" }); } catch (er) { showError(er); } finally { camBusy = false; paint(); }
    }
  };
}

function onEvent(type, data) {
  if (!root) return;
  if (type === "audit") {
    if (data.phase === "done") { progress = null; S.audit_last = data.report; }
    else if (data.phase === "error") { progress = null; showError({ key: "audit_failed" }); }
    else progress = data;
    paint();
  }
  if (type === "license") paint();
}

export default { render, onEvent, destroy() { root = null; } };
export { loadingBtn };
