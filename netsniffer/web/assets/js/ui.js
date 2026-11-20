// UI primitives. Every interpolated value in html`` is HTML-escaped unless wrapped in raw().
import { icon } from "./icons.js";

export class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = (s) => new Raw(String(s ?? ""));
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;" };
export const esc = (s) => String(s ?? "").replace(/[&<>"'`]/g, (c) => ESC[c]);

function val(v) {
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(val).join("");
  if (v === null || v === undefined || v === false) return "";
  return esc(v);
}
export function html(strings, ...vals) {
  let out = "";
  strings.forEach((s, i) => { out += s; if (i < vals.length) out += val(vals[i]); });
  return new Raw(out);
}
export const ico = (name, cls) => raw(icon(name, cls));
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function debounce(fn, ms = 200) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// ------------------------------------------------------------------ toasts
export function toast({ title, text = "", kind = "info", iconName, timeout = 4200, action } = {}) {
  const box = $("#toasts");
  const el = document.createElement("div");
  const ic = iconName || { info: "info", ok: "checkCircle", warning: "alert", critical: "shieldAlert", error: "alert" }[kind] || "info";
  el.className = "toast";
  el.setAttribute("role", "status");
  el.innerHTML = html`<span class="ev-ico ${kind === "error" ? "critical" : kind}">${ico(ic)}</span>
    <div style="flex:1;min-width:0"><div class="t-t">${title}</div>${text ? html`<div class="t-d">${text}</div>` : ""}
    ${action ? html`<button class="btn xs" style="margin-top:8px" data-act>${action.label}</button>` : ""}</div>
    <button class="icon-btn" style="width:26px;height:26px" aria-label="close">${ico("x")}</button>`;
  box.appendChild(el);
  const close = () => { el.classList.add("out"); setTimeout(() => el.remove(), 260); };
  el.querySelector("button[aria-label]").onclick = close;
  if (action) el.querySelector("[data-act]").onclick = () => { action.run(); close(); };
  if (timeout) setTimeout(close, timeout);
  while (box.children.length > 4) box.firstChild.remove();
  return close;
}

// ------------------------------------------------------------------ modal
export function openModal({ title, desc, body = "", footer = "", wide = false, onMount, dismissible = true, iconName } = {}) {
  const wrap = document.createElement("div");
  wrap.className = "modal-wrap";
  wrap.innerHTML = html`<div class="scrim"></div><div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true">
    ${title ? html`<div class="modal-h">${iconName ? html`<span class="ev-ico info">${ico(iconName)}</span>` : ""}
      <div style="flex:1"><h3>${title}</h3>${desc ? html`<p>${desc}</p>` : ""}</div>
      ${dismissible ? html`<button class="icon-btn" data-close aria-label="close">${ico("x")}</button>` : ""}</div>` : ""}
    <div class="modal-b">${body}</div>${footer ? html`<div class="modal-f">${footer}</div>` : ""}</div>`;
  document.body.appendChild(wrap);
  const modal = wrap.querySelector(".modal"), scrim = wrap.querySelector(".scrim");
  requestAnimationFrame(() => { modal.classList.add("show"); scrim.classList.add("show"); });
  let closed = false;
  const close = () => {
    if (closed) return; closed = true;
    modal.classList.remove("show"); scrim.classList.remove("show");
    document.removeEventListener("keydown", onKey);
    setTimeout(() => wrap.remove(), 220);
  };
  const onKey = (e) => { if (e.key === "Escape" && dismissible) close(); };
  document.addEventListener("keydown", onKey);
  if (dismissible) { scrim.onclick = close; wrap.querySelectorAll("[data-close]").forEach((b) => (b.onclick = close)); }
  onMount?.(modal, close);
  setTimeout(() => modal.querySelector("input:not([type=checkbox]),select,textarea")?.focus(), 60);
  return { el: modal, close };
}

export function confirmDialog({ title, text, ok, cancel, danger = false }) {
  return new Promise((resolve) => {
    const m = openModal({
      title, desc: text,
      footer: html`<button class="btn" data-no>${cancel}</button><button class="btn ${danger ? "danger solid" : "primary"}" data-yes>${ok}</button>`,
      onMount: (el, close) => {
        el.querySelector("[data-no]").onclick = () => { close(); resolve(false); };
        el.querySelector("[data-yes]").onclick = () => { close(); resolve(true); };
      },
    });
    m.el.querySelector("[data-yes]")?.focus();
  });
}

// ------------------------------------------------------------------ dropdown menu
export function openMenu(anchor, items) {
  document.querySelectorAll(".menu").forEach((m) => m.remove());
  const m = document.createElement("div");
  m.className = "menu";
  m.innerHTML = items.map((it, i) => it.sep ? '<div class="sep" style="margin:5px 0"></div>' :
    html`<button data-i="${i}" class="${it.on ? "on" : ""}">${it.icon ? ico(it.icon) : ""}<span>${it.label}</span></button>`.s).join("");
  document.body.appendChild(m);
  const r = anchor.getBoundingClientRect();
  const w = m.offsetWidth, h = m.offsetHeight;
  m.style.left = Math.max(8, Math.min(r.right - w, innerWidth - w - 8)) + "px";
  m.style.top = (r.bottom + 6 + h > innerHeight ? r.top - h - 6 : r.bottom + 6) + "px";
  const close = () => { m.remove(); document.removeEventListener("pointerdown", outside, true); };
  const outside = (e) => { if (!m.contains(e.target)) close(); };
  setTimeout(() => document.addEventListener("pointerdown", outside, true));
  m.onclick = (e) => {
    const b = e.target.closest("button[data-i]"); if (!b) return;
    close(); items[+b.dataset.i].action?.();
  };
}

// ------------------------------------------------------------------ drawer
let drawerState = null;
export function openDrawer(render, onClose) {
  closeDrawer(true);
  const scrim = document.createElement("div"); scrim.className = "scrim";
  const d = document.createElement("aside"); d.className = "drawer"; d.setAttribute("role", "dialog");
  document.body.append(scrim, d);
  const set = (content) => { d.innerHTML = String(content); };
  set(render());
  requestAnimationFrame(() => { scrim.classList.add("show"); d.classList.add("show"); });
  const onKey = (e) => { if (e.key === "Escape" && !document.querySelector(".modal-wrap")) closeDrawer(); };
  document.addEventListener("keydown", onKey);
  scrim.onclick = () => closeDrawer();
  drawerState = { scrim, d, onKey, onClose };
  return { el: d, set };
}
export function closeDrawer(silent = false) {
  if (!drawerState) return;
  const { scrim, d, onKey, onClose } = drawerState;
  drawerState = null;
  d.classList.remove("show"); scrim.classList.remove("show");
  document.removeEventListener("keydown", onKey);
  setTimeout(() => { d.remove(); scrim.remove(); }, 300);
  if (!silent) onClose?.();
}
export const drawerOpen = () => !!drawerState;

export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; }
  catch {
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    const ok = document.execCommand("copy"); ta.remove(); return ok;
  }
}

export function loadingBtn(btn, on) {
  if (!btn) return;
  if (on) { btn.dataset.html = btn.innerHTML; btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>' + btn.innerHTML.replace(/<svg[\s\S]*?<\/svg>/, ""); }
  else { btn.disabled = false; if (btn.dataset.html) btn.innerHTML = btn.dataset.html; }
}
