// Device detail drawer.
import { api } from "../api.js";
import { deviceAvatar, deviceBadges, deviceSub, EVENT_ICON, eventClass, eventText, showError } from "../common.js";
import { fmt, t } from "../i18n.js";
import { TYPES } from "../icons.js";
import { S, on, upsertDevice } from "../store.js";
import { closeDrawer, confirmDialog, copyText, html, ico, loadingBtn, openDrawer, openMenu, openModal, toast } from "../ui.js";

let cur = null, tab = "overview", drawer = null, off = [], portProgress = null, pingRes = null;

function kv(label, value, copy) {
  return html`<div>${label}</div><div>${value || html`<span class="faint">—</span>`}${copy && value ? html`<span class="copy" data-copy="${copy}" title="${t("common.copy")}">${ico("copy")}</span>` : ""}</div>`;
}

function overview(d) {
  const ex = d.extra || {};
  const txt = ex.mdns_txt || {};
  const ssdp = d.ssdp || {};
  return html`<div class="kv-grid">
    ${kv(t("device.ip"), html`<span class="mono">${d.ip}</span>`, d.ip)}
    ${kv("MAC", d.mac ? html`<span class="mono">${d.mac}</span>${d.randomized ? html` <span class="badge" title="${t("device.private_mac_hint")}">${t("device.private")}</span>` : ""}` : "", d.mac)}
    ${kv(t("device.vendor"), d.vendor || (d.randomized ? t("device.private_mac") : ""))}
    ${kv(t("device.model"), d.model || ssdp.model)}
    ${kv(t("device.type"), html`<select class="input" id="d-type" style="height:32px;width:auto">${TYPES.map((x) => html`<option value="${x}" ${d.type === x ? "selected" : ""}>${t(`types.${x}`)}</option>`)}</select>`)}
    ${kv(t("device.os"), d.os)}
    ${kv(t("device.hostname"), d.hostname)}
    ${d.mdns_name ? kv("mDNS", d.mdns_name) : ""}
    ${d.netbios ? kv("NetBIOS", d.netbios + (ex.workgroup ? ` · ${ex.workgroup}` : "")) : ""}
    ${ssdp.friendly_name ? kv("UPnP", `${ssdp.friendly_name}${ssdp.manufacturer ? ` · ${ssdp.manufacturer}` : ""}`) : ""}
    ${ssdp.server ? kv(t("device.server"), ssdp.server) : ""}
    ${kv(t("device.first_seen"), fmt.date(d.first_seen))}
    ${kv(t("device.last_seen"), d.online ? t("device.online_now") : fmt.date(d.last_seen))}
    ${d.services?.length ? kv(t("device.services"), html`<span class="row wrap" style="gap:5px">${d.services.map((s) => html`<span class="badge">${s.replace(/^_|\._(tcp|udp)$/g, "")}</span>`)}</span>`) : ""}
  </div>
  ${pingRes ? html`<div class="banner ${pingRes.received ? "accent" : "warn"}" style="margin-top:16px"><div class="b-ico">${ico("activity")}</div><div class="b-txt">
    <div class="b-t">${pingRes.received ? t("device.ping_ok", { avg: fmt.num(pingRes.avg, 1), min: fmt.num(pingRes.min, 1), max: fmt.num(pingRes.max, 1) }) : t("device.ping_fail")}</div>
    <div class="b-d">${t("device.ping_detail", { recv: pingRes.received, sent: pingRes.sent, method: pingRes.method.toUpperCase() })}</div></div></div>` : ""}
  <div class="sep"></div>
  <div class="field"><label>${t("device.notes")}</label><textarea class="input" id="d-notes" placeholder="${t("device.notes_ph")}">${d.notes || ""}</textarea></div>`;
}

function ports(d) {
  const list = d.ports || [];
  const riskCls = { critical: "danger", high: "danger", medium: "warn", low: "info", none: "ok" };
  return html`<div class="row wrap" style="margin-bottom:14px">
      <button class="btn sm primary" data-ports="quick">${ico("scan")} ${t("ports.quick")}</button>
      <button class="btn sm" data-ports="common">${ico("scan")} ${t("ports.common")}</button>
      <button class="btn sm" data-ports="full">${ico("scan")} ${t("ports.full")}</button>
      <span class="faint" style="font-size:12.5px">${d.ports_scanned ? t("ports.scanned", { ago: fmt.ago(d.ports_scanned) }) : t("ports.never")}</span></div>
    ${portProgress ? html`<div class="progress" style="margin-bottom:14px"><i style="width:${Math.round((portProgress.done / portProgress.total) * 100)}%"></i></div>` : ""}
    ${list.length ? html`<div class="card" style="box-shadow:none"><table class="table"><thead><tr><th>${t("ports.port")}</th><th>${t("ports.service")}</th><th>${t("ports.risk")}</th></tr></thead><tbody>
      ${list.map((p) => html`<tr style="cursor:default"><td class="mono">${p.port}/${p.proto}</td><td><b>${p.service}</b>${p.banner ? html`<div class="faint mono" style="font-size:11.5px">${p.banner}</div>` : ""}</td>
        <td><span class="badge ${riskCls[p.risk] || ""}">${t(`risk.${p.risk}`)}</span></td></tr>`)}</tbody></table></div>`
      : html`<div class="faint">${d.ports_scanned ? t("ports.none_open") : t("ports.hint")}</div>`}
    <p class="faint" style="font-size:12px;margin-top:14px">${ico("info")} ${t("ports.legal")}</p>`;
}

function activity(d) {
  const evs = d.events || [];
  if (!evs.length) return html`<div class="faint">${t("device.no_events")}</div>`;
  return html`<div class="timeline">${evs.map((ev) => {
    const { title } = eventText(ev);
    const cls = { device_online: "ok", device_offline: "bad", device_new: "warn", device_blocked: "bad" }[ev.kind] || "";
    return html`<div class="tl ${cls}"><div class="t">${title}</div><div class="s">${fmt.date(ev.ts)} · ${fmt.ago(ev.ts)}</div></div>`;
  })}</div>`;
}

function view() {
  const d = cur;
  if (!d) return html`<div class="drawer-b"><div class="skeleton" style="height:60px;margin-bottom:16px"></div><div class="skeleton" style="height:240px"></div></div>`;
  const web = (d.ports || []).concat((d.open_hint || []).map((p) => ({ port: p }))).find((p) => [80, 443, 8080, 8443, 5000, 8123, 32400].includes(p.port));
  const paused = d.pause_until && d.pause_until > Date.now() / 1000;
  return html`<div class="drawer-h">
    <div class="row" style="align-items:flex-start;gap:14px">${deviceAvatar(d, "lg")}
      <div style="flex:1;min-width:0">
        <div class="row" style="gap:6px"><h3 style="margin:0;font-size:19px;letter-spacing:-.02em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" id="d-name">${d.display_name}</h3>
          <button class="btn ghost xs" data-act="rename" aria-label="${t("common.rename")}">${ico("edit")}</button></div>
        <div class="faint" style="font-size:13px">${deviceSub(d)}</div>
        <div class="row wrap" style="gap:6px;margin-top:8px">${d.online ? html`<span class="badge ok"><span class="status-dot on"></span>${t("device.online")}</span>` : html`<span class="badge">${t("device.offline")} · ${fmt.ago(d.last_seen)}</span>`}
          ${deviceBadges(d)}${paused ? html`<span class="badge warn">${ico("pause")} ${t("parental.paused_until", { time: fmt.time(d.pause_until) })}</span>` : ""}</div>
      </div>
      <button class="icon-btn" data-act="close" aria-label="${t("common.close")}">${ico("x")}</button></div>
    <div class="actions" style="margin-top:16px">
      <button class="btn sm ${d.trusted ? "" : "primary"}" data-act="trust">${ico(d.trusted ? "shieldCheck" : "shield")} ${d.trusted ? t("device.trusted") : t("device.mark_trusted")}</button>
      <button class="btn sm" data-act="ping">${ico("activity")} Ping</button>
      ${!d.is_self && !d.is_gateway ? html`<button class="btn sm ${d.blocked ? "danger solid" : "danger"}" data-act="block">${ico(d.blocked ? "unlock" : "ban")} ${d.blocked ? t("device.unblock") : t("device.block")}</button>
        <button class="btn sm" data-act="pause">${ico("pause")} ${t("parental.pause")}</button>` : ""}
      ${d.mac && !d.is_self ? html`<button class="btn sm" data-act="wol">${ico("wake")} ${t("device.wake")}</button>` : ""}
      ${web ? html`<a class="btn sm" href="${web.port === 443 || web.port === 8443 ? "https" : "http"}://${d.ip}${[80, 443].includes(web.port) ? "" : ":" + web.port}" target="_blank" rel="noopener noreferrer">${ico("external")} ${t("device.open_web")}</a>` : ""}
      <button class="btn sm icon" data-act="fav" aria-label="${t("device.favorite")}" title="${t("device.favorite_hint")}" style="${d.favorite ? "color:var(--warn)" : ""}">${ico("star")}</button>
      <button class="btn sm icon" data-act="more" aria-label="${t("common.more")}">${ico("more")}</button>
    </div>
    <div class="tabs" style="margin-top:16px;margin-bottom:-15px">${["overview", "ports", "activity"].map((x) => html`<button class="${tab === x ? "on" : ""}" data-tab="${x}">${t(`device.tab_${x}`)}${x === "ports" && d.ports?.length ? html` <span class="badge">${d.ports.length}</span>` : ""}</button>`)}</div>
  </div>
  <div class="drawer-b">${tab === "overview" ? overview(d) : tab === "ports" ? ports(d) : activity(d)}</div>`;
}

function paint() { drawer?.set(view()); }

async function load(id) {
  try { cur = await api(`/devices/${encodeURIComponent(id)}`); upsertDevice(cur); paint(); }
  catch (e) { showError(e); closeDrawer(); }
}

async function patch(fields) {
  try { const d = await api(`/devices/${encodeURIComponent(cur.id)}`, { method: "PATCH", body: fields }); cur = { ...cur, ...d }; upsertDevice(d); paint(); window.dispatchEvent(new Event("ns:devices-changed")); }
  catch (e) { showError(e); }
}

export function blockGuide(d) {
  openModal({
    title: t("block.guide_title"), desc: t("block.guide_desc"), iconName: "ban", wide: true,
    body: html`<div class="stack" style="gap:10px">
      ${["ssh", "fritz", "local"].map((b) => html`<div class="banner"><div class="b-ico">${ico(b === "fritz" ? "t_router" : b === "ssh" ? "terminal" : "t_raspberry")}</div>
        <div class="b-txt"><div class="b-t">${t(`block.backend_${b}`)}</div><div class="b-d">${t(`block.backend_${b}_d`)}</div></div></div>`)}
      ${d?.mac ? html`<div class="banner warn"><div class="b-ico">${ico("info")}</div><div class="b-txt"><div class="b-t">${t("block.manual_t")}</div>
        <div class="b-d">${t("block.manual_d")} <b class="mono">${d.mac}</b> <span class="copy" data-copy="${d.mac}">${ico("copy")}</span></div></div></div>` : ""}</div>`,
    footer: html`<button class="btn" data-close>${t("common.close")}</button><a class="btn primary" href="#/settings/blocking" data-close>${ico("settings")} ${t("block.configure")}</a>`,
    onMount: (el, close) => {
      el.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", close));
      el.addEventListener("click", (e) => { const c = e.target.closest("[data-copy]"); if (c) copyText(c.dataset.copy).then(() => toast({ kind: "ok", title: t("common.copied") })); });
    },
  });
}

async function act(name, btn) {
  const d = cur, id = encodeURIComponent(d.id);
  try {
    switch (name) {
      case "close": closeDrawer(); break;
      case "trust": await patch({ trusted: !d.trusted }); break;
      case "fav": await patch({ favorite: !d.favorite }); break;
      case "rename": {
        const m = openModal({
          title: t("common.rename"), body: html`<input class="input" id="nm" value="${d.name || d.display_name}" maxlength="64">`,
          footer: html`<button class="btn" data-close>${t("common.cancel")}</button><button class="btn primary" id="ok">${t("common.save")}</button>`,
          onMount: (el, close) => {
            const save = () => { patch({ name: el.querySelector("#nm").value }); close(); };
            el.querySelector("#ok").onclick = save; el.querySelector("#nm").onkeydown = (e) => e.key === "Enter" && save();
          },
        });
        m.el.querySelector("#nm").select();
        break;
      }
      case "ping": loadingBtn(btn, true); pingRes = await api(`/devices/${id}/ping`, { method: "POST" }); tab = "overview"; paint(); break;
      case "wol": await api(`/devices/${id}/wol`, { method: "POST" }); toast({ kind: "ok", title: t("device.wol_sent"), text: d.mac }); break;
      case "block": {
        if (!d.blocked && !(await confirmDialog({ title: t("device.block_confirm_t", { name: d.display_name }), text: t("device.block_confirm"), ok: t("device.block"), cancel: t("common.cancel"), danger: true }))) return;
        loadingBtn(btn, true);
        const r = await api(`/devices/${id}/block`, { method: "POST", body: { blocked: !d.blocked } });
        cur = { ...cur, ...r }; upsertDevice(r); paint();
        toast({ kind: "ok", title: r.blocked ? t("device.blocked_ok") : t("device.unblocked_ok") });
        break;
      }
      case "pause": {
        const opts = [[15, "15 min"], [60, "1 h"], [120, "2 h"], [480, "8 h"]];
        openMenu(btn, [...opts.map(([m, l]) => ({ label: t("parental.pause_for", { d: l }), icon: "pause", action: () => pause(m) })),
          { sep: true }, { label: t("parental.resume"), icon: "play", action: () => pause(0) }]);
        break;
      }
      case "more":
        openMenu(btn, [
          { label: t("common.copy") + " IP", icon: "copy", action: () => copyText(d.ip).then(() => toast({ kind: "ok", title: t("common.copied") })) },
          d.mac && { label: t("common.copy") + " MAC", icon: "copy", action: () => copyText(d.mac).then(() => toast({ kind: "ok", title: t("common.copied") })) },
          { sep: true },
          { label: t("device.forget"), icon: "trash", action: forget },
        ].filter(Boolean));
        break;
    }
  } catch (e) {
    if (e.key === "block_not_configured") blockGuide(d); else showError(e);
  } finally { loadingBtn(btn, false); }
}

async function pause(minutes) {
  try {
    const r = await api(`/devices/${encodeURIComponent(cur.id)}/pause`, { method: "POST", body: { minutes } });
    cur.pause_until = r.until; paint();
    toast({ kind: "ok", title: minutes ? t("parental.paused_ok") : t("parental.resumed_ok") });
  } catch (e) { if (e.key === "block_not_configured") blockGuide(cur); else showError(e); }
}

async function forget() {
  if (!(await confirmDialog({ title: t("device.forget"), text: t("device.forget_text"), ok: t("common.delete"), cancel: t("common.cancel"), danger: true }))) return;
  await api(`/devices/${encodeURIComponent(cur.id)}`, { method: "DELETE" }).catch(showError);
  S.devices = S.devices.filter((x) => x.id !== cur.id);
  closeDrawer();
}

async function scanPorts(profile, btn) {
  loadingBtn(btn, true);
  portProgress = { done: 0, total: 1 }; paint();
  try { const r = await api(`/devices/${encodeURIComponent(cur.id)}/ports`, { method: "POST", body: { profile } }); cur = { ...cur, ...r }; }
  catch (e) { showError(e); }
  finally { portProgress = null; tab = "ports"; paint(); }
}

export function openDevice(id) {
  cur = S.devices.find((d) => d.id === id) || null; tab = "overview"; pingRes = null; portProgress = null;
  const prevHash = location.hash.startsWith("#/devices/") ? "#/devices" : location.hash || "#/dashboard";
  history.replaceState(null, "", `#/devices/${encodeURIComponent(id)}`);
  drawer = openDrawer(view, () => {
    off.forEach((f) => f()); off = []; drawer = null; cur = null;
    if (location.hash.startsWith("#/devices/")) history.replaceState(null, "", prevHash);
  });
  const el = drawer.el;
  el.addEventListener("click", (e) => {
    const a = e.target.closest("[data-act]"); if (a) return act(a.dataset.act, a);
    const tb = e.target.closest("[data-tab]"); if (tb) { tab = tb.dataset.tab; return paint(); }
    const p = e.target.closest("[data-ports]"); if (p) return scanPorts(p.dataset.ports, p);
    const c = e.target.closest("[data-copy]"); if (c) copyText(c.dataset.copy).then(() => toast({ kind: "ok", title: t("common.copied") }));
  });
  el.addEventListener("change", (e) => { if (e.target.id === "d-type") patch({ type: e.target.value }); });
  el.addEventListener("focusout", (e) => { if (e.target.id === "d-notes" && e.target.value !== (cur.notes || "")) patch({ notes: e.target.value }); });
  off.push(on("ports_progress", (p) => { if (cur && p.device_id === cur.id && portProgress) { portProgress = p; const bar = el.querySelector(".progress i"); if (bar) bar.style.width = Math.round((p.done / p.total) * 100) + "%"; } }));
  off.push(on("device", (d) => { if (cur && d.id === cur.id && !el.contains(document.activeElement)) { cur = { ...cur, ...d }; paint(); } }));
  load(id);
}
