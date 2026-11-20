import { api } from "../api.js";
import { showError } from "../common.js";
import { getLang, LANGS, t, fmt } from "../i18n.js";
import { applyTheme, changeLang, saveSettings } from "../main.js";
import { S } from "../store.js";
import { $, confirmDialog, copyText, html, ico, loadingBtn, openModal, toast } from "../ui.js";

let root;
const SECTIONS = ["general", "scanning", "notifications", "remote", "blocking", "updates", "privacy", "about"];

const sw = (key, { disabled = false } = {}) => html`<label class="switch"><input type="checkbox" data-key="${key}" ${S.settings[key] ? "checked" : ""} ${disabled ? "disabled" : ""}><span></span></label>`;
const row = (title, desc, ctl) => html`<div class="setting"><div class="txt"><div class="t">${title}</div>${desc ? html`<div class="d">${desc}</div>` : ""}</div><div class="ctl">${ctl}</div></div>`;
const card = (id, iconName, title, body, sub = "") => html`<section class="card" id="sec-${id}"><div class="card-h"><span class="ev-ico info">${ico(iconName)}</span><div><h3>${title}</h3>${sub ? html`<div class="sub">${sub}</div>` : ""}</div></div><div class="card-b">${body}</div></section>`;

function general() {
  const s = S.settings;
  return card("general", "settings", t("settings.general"), html`
    ${row(t("settings.language"), t("settings.language_d"), html`<select class="input" data-lang style="width:200px"><option value="auto" ${s.language === "auto" ? "selected" : ""}>${t("settings.lang_auto")} (${LANGS[getLang()]})</option>
      ${Object.entries(LANGS).map(([k, v]) => html`<option value="${k}" ${s.language === k ? "selected" : ""}>${v}</option>`)}</select>`)}
    ${row(t("settings.theme"), t("settings.theme_d"), html`<div class="seg">${[["system", "monitorSys"], ["light", "sun"], ["dark", "moon"]].map(([k, i]) =>
      html`<button class="${(s.theme || "system") === k ? "on" : ""}" data-theme="${k}">${ico(i)}${t(`settings.theme_${k}`)}</button>`)}</div>`)}`);
}

function scanning() {
  const s = S.settings;
  return card("scanning", "radar", t("settings.scanning"), html`
    ${row(t("settings.auto_scan"), t("settings.auto_scan_d"), sw("auto_scan"))}
    ${row(t("settings.interval"), t("settings.interval_d"), html`<select class="input" data-key="scan_interval_min" style="width:140px">
      ${[1, 2, 5, 10, 15, 30, 60, 120].map((m) => html`<option value="${m}" ${+s.scan_interval_min === m ? "selected" : ""}>${m} min</option>`)}</select>`)}
    ${row(t("settings.watcher"), t("settings.watcher_d"), sw("watcher"))}
    ${row(t("settings.monitor_interval"), t("settings.monitor_interval_d"), html`<select class="input" data-key="monitor_interval_s" style="width:140px">
      ${[5, 10, 15, 30, 60].map((v) => html`<option value="${v}" ${+s.monitor_interval_s === v ? "selected" : ""}>${v} s</option>`)}</select>`)}`);
}

function notifications() {
  const s = S.settings;
  return card("notifications", "bell", t("settings.notifications"), html`
    ${row(t("settings.n_desktop"), t("settings.n_desktop_d"), sw("notify_desktop"))}
    ${row(t("settings.n_new"), t("settings.n_new_d"), sw("notify_new_device"))}
    ${row(t("settings.n_offline"), t("settings.n_offline_d"), sw("notify_device_offline"))}
    ${row(t("settings.n_internet"), t("settings.n_internet_d"), sw("notify_internet"))}
    ${row(t("settings.n_security"), t("settings.n_security_d"), sw("notify_security"))}
    <div class="sep"></div><div class="label" style="margin-bottom:10px">${t("settings.n_push")}</div>
    <div class="form-grid">
      <div class="field"><label>ntfy URL</label><input class="input" data-key="notify_ntfy_url" value="${s.notify_ntfy_url}" placeholder="https://ntfy.sh/my-home-alerts"></div>
      <div class="field"><label>Webhook URL</label><input class="input" data-key="notify_webhook_url" value="${s.notify_webhook_url}" placeholder="https://…"></div>
      <div class="field"><label>Telegram bot token</label><input class="input" type="password" data-key="notify_telegram_token" value="${s.notify_telegram_token}" autocomplete="off"></div>
      <div class="field"><label>Telegram chat ID</label><input class="input" data-key="notify_telegram_chat" value="${s.notify_telegram_chat}"></div>
    </div>
    <div class="row" style="margin-top:14px"><button class="btn sm" id="n-test">${ico("bell")} ${t("settings.n_test")}</button><span class="faint" style="font-size:12.5px">${t("settings.n_push_d")}</span></div>`);
}

function remote() {
  const r = S.remote || {};
  const dark = document.documentElement.dataset.theme === "dark";
  return card("remote", "globe", t("settings.remote"), html`
    ${S.app.headless ? html`<div class="banner accent" style="margin-bottom:10px"><div class="b-ico">${ico("t_raspberry")}</div><div class="b-txt"><div class="b-t">${t("settings.remote_headless")}</div></div></div>` :
      row(t("settings.remote_enable"), t("settings.remote_enable_d"), sw("remote_enabled", { disabled: !r.password_set }))}
    ${row(t("settings.remote_password"), r.password_set ? t("settings.remote_password_set") : t("settings.remote_password_d"), html`<button class="btn sm" id="r-pass">${ico("key")} ${r.password_set ? t("common.change") : t("common.set")}</button>`)}
    ${S.app.headless ? "" : row(t("settings.remote_port"), "", html`<input class="input" type="number" min="1024" max="65535" data-key="remote_port" value="${S.settings.remote_port}" style="width:110px">`)}
    ${r.running && r.urls?.length ? html`<div class="sep"></div><div class="row wrap" style="gap:20px;align-items:center">
      <div class="qr"><img src="/api/remote/qr.svg?dark=${dark}" alt="QR"></div>
      <div style="flex:1;min-width:220px"><div class="label">${t("settings.remote_open")}</div>
        ${r.urls.map((u) => html`<div class="row" style="margin-top:6px"><b class="mono" style="font-size:15px">${u}</b><span class="copy" data-copy="${u}">${ico("copy")}</span></div>`)}
        <p class="faint" style="font-size:12.5px">${t("settings.remote_hint")}</p></div></div>` : ""}`);
}

function blocking() {
  const s = S.settings, b = s.block_backend || "none";
  const st = S.blocking || {};
  return card("blocking", "ban", t("settings.blocking"), html`
    <p class="muted" style="margin-top:0;font-size:13.5px">${t("block.intro")}</p>
    <div class="field"><label>${t("block.backend")}</label><select class="input" data-key="block_backend">
      ${["none", "ssh", "fritz", "local"].map((k) => html`<option value="${k}" ${b === k ? "selected" : ""}>${t(`block.backend_${k}`)}</option>`)}</select>
      <div class="hint">${b !== "none" ? t(`block.backend_${b}_d`) : t("block.none_d")}</div></div>
    ${b === "ssh" || b === "fritz" ? html`<div class="form-grid" style="margin-top:14px">
      <div class="field"><label>${t("block.host")}</label><input class="input mono" data-key="block_host" value="${s.block_host}" placeholder="${S.network.gateway || "192.168.1.1"}"></div>
      ${b === "ssh" ? html`<div class="field"><label>${t("block.port")}</label><input class="input" type="number" data-key="block_port" value="${s.block_port}"></div>` : html`<div></div>`}
      <div class="field"><label>${t("block.user")}</label><input class="input" data-key="block_user" value="${s.block_user}" autocomplete="off"></div>
      <div class="field"><label>${t("block.password")}</label><input class="input" type="password" data-key="block_password" value="${s.block_password}" autocomplete="new-password"></div>
    </div>` : ""}
    ${b === "ssh" || b === "local" ? html`<div class="field" style="margin-top:14px"><label>${t("block.firewall")}</label><select class="input" data-key="block_firewall" style="width:220px">
      <option value="nft" ${s.block_firewall === "nft" ? "selected" : ""}>nftables (OpenWrt 22+)</option><option value="iptables" ${s.block_firewall === "iptables" ? "selected" : ""}>iptables</option></select></div>` : ""}
    ${b !== "none" ? html`<div class="row wrap" style="margin-top:16px"><button class="btn sm primary" id="b-test">${ico("link")} ${t("block.test")}</button>
      ${st.last_error ? html`<span class="badge danger">${st.last_error}</span>` : st.last_apply ? html`<span class="badge ok">${ico("check")} ${t("block.applied", { ago: fmt.ago(st.last_apply) })}</span>` : ""}</div>` : ""}
    <p class="faint" style="font-size:12px;margin-bottom:0">${ico("info")} ${t("block.legal")}</p>`);
}

function updates() {
  const u = S.update || {};
  const status = u.status === "available" ? t("update.available", { v: u.latest }) : u.status === "ready" ? t("update.ready_title", { v: u.latest })
    : u.status === "downloading" ? t("update.downloading", { p: Math.round((u.progress || 0) * 100) }) : u.status === "error" ? t("update.error")
      : u.status === "checking" ? t("update.checking") : t("update.uptodate");
  return card("updates", "download", t("settings.updates"), html`
    ${row(t("update.current", { v: S.app.version }), html`${status}${u.checked ? ` · ${t("update.checked", { ago: fmt.ago(u.checked) })}` : ""}`,
      html`<button class="btn sm" id="u-check">${ico("refresh")} ${t("update.check")}</button>${u.available && u.can_apply ? html`<button class="btn sm primary" id="u-apply">${ico("download")} ${t("update.install")}</button>` : ""}`)}
    ${u.status === "downloading" ? html`<div class="progress"><i style="width:${Math.round((u.progress || 0) * 100)}%"></i></div>` : ""}
    ${row(t("update.auto"), t("update.auto_d"), sw("auto_update"))}
    ${u.available && !u.can_apply ? html`<div class="banner info"><div class="b-ico">${ico("info")}</div><div class="b-txt"><div class="b-d">${t("update.source_mode")}</div></div></div>` : ""}
    ${u.notes && u.available ? html`<details style="margin-top:10px"><summary class="label" style="cursor:pointer">${t("update.notes")}</summary><pre class="mono" style="white-space:pre-wrap;font-size:12px;color:var(--text-2)">${u.notes}</pre></details>` : ""}`);
}

function privacy() {
  return card("privacy", "lock", t("settings.privacy"), html`
    ${row(t("settings.public_ip"), t("settings.public_ip_d"), sw("public_ip_lookup"))}
    ${row(t("settings.clear_alerts"), t("settings.clear_alerts_d"), html`<button class="btn sm danger" id="clear-ev">${ico("trash")} ${t("alerts.clear")}</button>`)}
    ${S.app.headless || S.remote?.password_set ? row(t("settings.logout"), t("settings.logout_d"), html`<button class="btn sm" id="logout">${ico("logout")} ${t("settings.logout")}</button>`) : ""}`);
}

function about() {
  return card("about", "info", t("settings.about"), html`<div class="row" style="gap:14px"><div class="brand-logo" style="width:48px;height:48px;border-radius:14px">${ico("logo")}</div>
    <div><b style="font-size:16px">NET Sniffer ${S.app.version}</b><div class="faint">${t("app.tagline")} · ${S.app.platform}${S.app.headless ? " · headless" : ""}</div></div></div>
    <p class="muted" style="font-size:13px">${t("settings.legal")}</p>
    <p class="faint" style="font-size:12px;margin-bottom:0">${t("settings.oss")}</p>`);
}

function paint() {
  if (!root) return;
  const y = $("#content").scrollTop;
  root.innerHTML = html`<div class="row wrap" style="gap:6px;margin-bottom:16px">${SECTIONS.map((s) => html`<button class="chip" data-go="${s}">${t(`settings.${s}`)}</button>`)}</div>
    <div class="stack" style="max-width:980px">${general()}${scanning()}${notifications()}${remote()}${blocking()}${updates()}${privacy()}${about()}</div>`;
  $("#content").scrollTop = y;
}

async function save(patch) {
  try { await saveSettings(patch); toast({ kind: "ok", title: t("settings.saved"), timeout: 1600 }); paint(); }
  catch (e) { showError(e); paint(); }
}

function passwordModal() {
  openModal({
    title: t("settings.remote_password"), desc: t("settings.remote_password_d"), iconName: "key",
    body: html`<div class="field"><label>${t("login.password")}</label><input class="input" type="password" id="p1" minlength="8" autocomplete="new-password"></div>
      <div class="field" style="margin-top:12px"><label>${t("login.repeat")}</label><input class="input" type="password" id="p2" autocomplete="new-password"></div>`,
    footer: html`<button class="btn" data-close>${t("common.cancel")}</button><button class="btn primary" id="p-ok">${t("common.save")}</button>`,
    onMount: (el, close) => {
      el.querySelector("#p-ok").onclick = async () => {
        const a = el.querySelector("#p1").value, b = el.querySelector("#p2").value;
        if (a.length < 8) return showError({ key: "password_short" });
        if (a !== b) return showError({ key: "password_mismatch" });
        try { const r = await api("/settings/remote-password", { method: "POST", body: { password: a } }); S.remote = r.remote; close(); toast({ kind: "ok", title: t("settings.saved") }); paint(); }
        catch (e) { showError(e); }
      };
    },
  });
}

function render(el, arg) {
  root = el; paint();
  if (arg) setTimeout(() => $(`#sec-${arg}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  el.onclick = async (e) => {
    const go = e.target.closest("[data-go]"); if (go) return $(`#sec-${go.dataset.go}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    const th = e.target.closest("[data-theme]"); if (th) { applyTheme(th.dataset.theme); return save({ theme: th.dataset.theme }); }
    const cp = e.target.closest("[data-copy]"); if (cp) return copyText(cp.dataset.copy).then(() => toast({ kind: "ok", title: t("common.copied") }));
    const id = e.target.closest("button")?.id;
    try {
      if (id === "n-test") { await api("/settings/notify-test", { method: "POST" }); toast({ kind: "ok", title: t("settings.n_test_sent") }); }
      if (id === "r-pass") passwordModal();
      if (id === "b-test") { const b = e.target.closest("button"); loadingBtn(b, true); try { const r = await api("/blocking/test", { method: "POST" }); toast({ kind: "ok", title: t("block.test_ok"), text: r.info }); } finally { loadingBtn(b, false); } }
      if (id === "u-check") { S.update = await api("/update/check", { method: "POST" }); paint(); }
      if (id === "u-apply") { await api("/update/apply", { method: "POST" }); toast({ kind: "ok", title: t("update.restarting") }); }
      if (id === "clear-ev" && (await confirmDialog({ title: t("alerts.clear"), text: t("alerts.clear_text"), ok: t("common.delete"), cancel: t("common.cancel"), danger: true }))) {
        await api("/events", { method: "DELETE" }); toast({ kind: "ok", title: t("settings.saved") });
      }
      if (id === "logout") { await api("/auth/logout", { method: "POST" }); location.reload(); }
    } catch (er) { showError(er); }
  };
  el.onchange = (e) => {
    const tgt = e.target;
    if (tgt.matches("[data-lang]")) return changeLang(tgt.value);
    const key = tgt.dataset.key; if (!key) return;
    const v = tgt.type === "checkbox" ? tgt.checked : tgt.type === "number" || tgt.tagName === "SELECT" && /^\d+$/.test(tgt.value) ? +tgt.value : tgt.value;
    save({ [key]: v });
  };
}

function onEvent(type) {
  if (!root) return;
  if (["update", "settings", "blocking"].includes(type) && !root.contains(document.activeElement)) paint();
}
export default { render, onEvent, destroy() { root = null; } };
