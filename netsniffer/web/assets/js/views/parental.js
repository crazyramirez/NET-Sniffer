import { api } from "../api.js";
import { deviceAvatar, deviceSub, emptyState, proLock, showError } from "../common.js";
import { fmt, t } from "../i18n.js";
import { S } from "../store.js";
import { confirmDialog, html, ico, openModal, toast } from "../ui.js";
import { blockGuide } from "./device.js";

let root, rules = [], blocking = {};
const PRESETS = {
  bedtime: { days: [0, 1, 2, 3, 4, 5, 6], start: "22:00", end: "07:00" },
  school: { days: [0, 1, 2, 3, 4], start: "08:30", end: "14:30" },
  homework: { days: [0, 1, 2, 3, 4], start: "17:00", end: "19:00" },
};

function schedText(slot) {
  const days = slot.days?.length === 7 ? t("parental.every_day") : slot.days?.length === 5 && slot.days.every((d) => d < 5) ? t("parental.weekdays")
    : (slot.days || []).map((d) => fmt.weekday(d)).join(" ");
  return `${days} · ${slot.start}–${slot.end}`;
}

function ruleCard(r) {
  const devs = r.devices.map((id) => S.devices.find((d) => d.id === id)).filter(Boolean);
  return html`<div class="card pad"><div class="row" style="align-items:flex-start">
    <span class="ev-ico ${r.active ? "critical" : "info"}">${ico(r.active ? "ban" : "calendar")}</span>
    <div style="flex:1;min-width:0"><div class="row" style="gap:8px"><b style="font-size:15px">${r.name}</b>
      ${r.active ? html`<span class="badge danger">${t("parental.blocking_now")}</span>` : r.enabled ? html`<span class="badge ok">${t("parental.scheduled")}</span>` : html`<span class="badge">${t("parental.disabled")}</span>`}</div>
      <div class="faint" style="font-size:13px;margin-top:2px">${r.schedule.length ? r.schedule.map(schedText).join(" · ") : t("parental.no_schedule")}</div>
      <div class="row wrap" style="gap:6px;margin-top:10px">${devs.length ? devs.map((d) => html`<span class="type-chip" style="cursor:default">${deviceAvatar(d, "sm")}${d.display_name}</span>`) : html`<span class="faint">${t("parental.no_devices")}</span>`}</div></div>
    <label class="switch" title="${t("parental.enabled")}"><input type="checkbox" data-toggle="${r.id}" ${r.enabled ? "checked" : ""}><span></span></label>
    <button class="btn sm icon" data-edit="${r.id}" aria-label="${t("common.edit")}">${ico("edit")}</button>
    <button class="btn sm icon danger" data-del="${r.id}" aria-label="${t("common.delete")}">${ico("trash")}</button></div></div>`;
}

function paint() {
  if (!root) return;
  const noBackend = !blocking.backend || blocking.backend === "none";
  const body = html`<div class="stack">
    ${noBackend ? html`<div class="banner warn"><div class="b-ico">${ico("info")}</div><div class="b-txt"><div class="b-t">${t("parental.need_backend")}</div><div class="b-d">${t("parental.need_backend_d")}</div></div>
      <button class="btn sm" id="guide">${t("common.learn_more")}</button><a class="btn sm primary" href="#/settings/blocking">${t("block.configure")}</a></div>`
      : blocking.last_error ? html`<div class="banner warn"><div class="b-ico">${ico("alert")}</div><div class="b-txt"><div class="b-t">${t("parental.backend_error")}</div><div class="b-d mono">${blocking.last_error}</div></div></div>` : ""}
    <div class="row between wrap"><div><h2 style="margin:0;font-size:18px">${t("parental.rules")}</h2><div class="faint">${t("parental.rules_d")}</div></div>
      <div class="row">${Object.keys(PRESETS).map((p) => html`<button class="btn sm" data-preset="${p}">${ico("plus")} ${t(`parental.preset_${p}`)}</button>`)}
      <button class="btn sm primary" id="new">${ico("plus")} ${t("parental.new_rule")}</button></div></div>
    ${rules.length ? html`<div class="stack" style="gap:12px">${rules.map(ruleCard)}</div>` : html`<div class="card">${emptyState("family", t("parental.none"), t("parental.none_d"))}</div>`}
    <div class="card"><div class="card-h"><h3>${t("parental.quick_pause")}</h3><span class="sub">${t("parental.quick_pause_d")}</span></div><div class="card-b"><div class="list">
      ${S.devices.filter((d) => !d.is_self && !d.is_gateway && ["phone", "tablet", "laptop", "desktop", "console", "tv", "streamer"].includes(d.type)).slice(0, 12).map((d) => html`
        <div class="li">${deviceAvatar(d, "sm")}<div class="li-main"><div class="li-t">${d.display_name}</div><div class="li-s">${deviceSub(d)}</div></div>
        <button class="btn xs" data-pause="${d.id}" data-min="60">${ico("pause")} 1 h</button><button class="btn xs" data-pause="${d.id}" data-min="0">${ico("play")}</button></div>`)}
    </div></div></div></div>`;
  root.innerHTML = proLock("parental", body).s;
}

function editor(rule = { name: "", devices: [], schedule: [{ ...PRESETS.bedtime }], enabled: true }) {
  const r = structuredClone(rule);
  const candidates = S.devices.filter((d) => !d.is_self && !d.is_gateway);
  const slotsHtml = () => r.schedule.map((s, i) => html`<div class="slot"><div class="days">${[0, 1, 2, 3, 4, 5, 6].map((d) =>
    html`<button type="button" class="${s.days.includes(d) ? "on" : ""}" data-day="${i}:${d}">${fmt.weekday(d)}</button>`)}</div>
    <input class="input" type="time" value="${s.start}" data-start="${i}"><input class="input" type="time" value="${s.end}" data-end="${i}">
    <button type="button" class="btn sm icon ghost" data-rm="${i}" aria-label="${t("common.delete")}">${ico("x")}</button></div>`);
  openModal({
    title: rule.id ? t("parental.edit_rule") : t("parental.new_rule"), wide: true, iconName: "family",
    body: html`<div class="stack" style="gap:14px">
      <div class="field"><label>${t("parental.rule_name")}</label><input class="input" id="r-name" value="${r.name}" placeholder="${t("parental.rule_name_ph")}" maxlength="60"></div>
      <div class="field"><label>${t("parental.devices")}</label><input class="input" id="r-q" placeholder="${t("devices.search")}" style="margin-bottom:6px">
        <div class="pick-list" id="r-devs">${candidates.map((d) => html`<label class="pick" data-name="${(d.display_name + " " + d.ip + " " + (d.vendor || "")).toLowerCase()}">
          <input type="checkbox" value="${d.id}" ${r.devices.includes(d.id) ? "checked" : ""}>${deviceAvatar(d, "sm")}<div style="min-width:0"><div style="font-weight:600">${d.display_name}</div><div class="faint" style="font-size:12px">${d.ip} · ${deviceSub(d)}</div></div></label>`)}</div></div>
      <div class="field"><label>${t("parental.block_periods")}</label><div id="r-slots">${slotsHtml()}</div>
        <button type="button" class="btn sm" id="r-add" style="align-self:flex-start">${ico("plus")} ${t("parental.add_period")}</button>
        <div class="hint">${t("parental.periods_hint")}</div></div></div>`,
    footer: html`<button class="btn" data-close>${t("common.cancel")}</button><button class="btn primary" id="r-save">${t("common.save")}</button>`,
    onMount: (el, close) => {
      const slots = el.querySelector("#r-slots");
      const redraw = () => (slots.innerHTML = slotsHtml().s);
      el.addEventListener("click", (e) => {
        const day = e.target.closest("[data-day]");
        if (day) { const [i, d] = day.dataset.day.split(":").map(Number); const s = r.schedule[i]; s.days = s.days.includes(d) ? s.days.filter((x) => x !== d) : [...s.days, d].sort(); redraw(); }
        const rm = e.target.closest("[data-rm]"); if (rm) { r.schedule.splice(+rm.dataset.rm, 1); redraw(); }
        if (e.target.closest("#r-add")) { r.schedule.push({ days: [0, 1, 2, 3, 4], start: "21:00", end: "07:00" }); redraw(); }
      });
      el.addEventListener("change", (e) => {
        if (e.target.dataset.start !== undefined) r.schedule[+e.target.dataset.start].start = e.target.value;
        if (e.target.dataset.end !== undefined) r.schedule[+e.target.dataset.end].end = e.target.value;
      });
      el.querySelector("#r-q").oninput = (e) => { const q = e.target.value.toLowerCase(); el.querySelectorAll(".pick").forEach((p) => (p.style.display = p.dataset.name.includes(q) ? "" : "none")); };
      el.querySelector("#r-save").onclick = async () => {
        r.name = el.querySelector("#r-name").value.trim() || t("parental.rule");
        r.devices = [...el.querySelectorAll("#r-devs input:checked")].map((x) => x.value);
        try {
          await api(rule.id ? `/parental/${rule.id}` : "/parental", { method: rule.id ? "PUT" : "POST", body: r });
          close(); toast({ kind: "ok", title: t("parental.saved") }); load();
        } catch (e) { showError(e); }
      };
    },
  });
}

async function load() {
  try { const r = await api("/parental"); rules = r.rules; blocking = r.blocking; paint(); } catch (e) { showError(e); }
}

function render(el) {
  root = el; blocking = S.blocking || {}; paint(); load();
  el.onclick = async (e) => {
    if (e.target.closest("#guide")) return blockGuide();
    if (e.target.closest("#new")) return editor();
    const pr = e.target.closest("[data-preset]");
    if (pr) return editor({ name: t(`parental.preset_${pr.dataset.preset}`), devices: [], schedule: [{ ...PRESETS[pr.dataset.preset], days: [...PRESETS[pr.dataset.preset].days] }], enabled: true });
    const ed = e.target.closest("[data-edit]"); if (ed) return editor(rules.find((x) => x.id === +ed.dataset.edit));
    const del = e.target.closest("[data-del]");
    if (del && (await confirmDialog({ title: t("parental.delete_rule"), text: t("parental.delete_rule_d"), ok: t("common.delete"), cancel: t("common.cancel"), danger: true }))) {
      await api(`/parental/${del.dataset.del}`, { method: "DELETE" }).catch(showError); load();
    }
    const pa = e.target.closest("[data-pause]");
    if (pa) {
      try { await api(`/devices/${encodeURIComponent(pa.dataset.pause)}/pause`, { method: "POST", body: { minutes: +pa.dataset.min } });
        toast({ kind: "ok", title: +pa.dataset.min ? t("parental.paused_ok") : t("parental.resumed_ok") }); }
      catch (er) { if (er.key === "block_not_configured") blockGuide(); else showError(er); }
    }
  };
  el.onchange = async (e) => {
    const tg = e.target.closest("[data-toggle]");
    if (tg) { const r = rules.find((x) => x.id === +tg.dataset.toggle); await api(`/parental/${r.id}`, { method: "PUT", body: { ...r, enabled: tg.checked } }).catch(showError); load(); }
  };
}
function onEvent(type, data) { if (root && type === "blocking") { blocking = data; paint(); } }
export default { render, onEvent, destroy() { root = null; } };
