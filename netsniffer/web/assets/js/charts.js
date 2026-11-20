// Lightweight responsive SVG charts (no dependencies).
import { esc } from "./ui.js";

let gid = 0;
const nice = (v) => {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v)), n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
};

export function ring(value, { size = 148, stroke = 12, color } = {}) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, v = Math.max(0, Math.min(100, value ?? 0));
  const col = color || (v >= 80 ? "var(--ok)" : v >= 60 ? "var(--warn)" : "var(--danger)");
  const id = "rg" + ++gid;
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" style="transform:rotate(-90deg)">
    <defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${col}"/><stop offset="1" stop-color="${col}" stop-opacity=".65"/></linearGradient></defs>
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--panel-3)" stroke-width="${stroke}"/>
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="url(#${id})" stroke-width="${stroke}" stroke-linecap="round"
      stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - v / 100)}" style="transition:stroke-dashoffset 1s cubic-bezier(.2,.8,.2,1)"/></svg>`;
}

export function sparkline(values, { color = "var(--accent)", h = 44 } = {}) {
  const vals = values.filter((v) => v !== null && v !== undefined);
  if (vals.length < 2) return "";
  const max = Math.max(...vals) * 1.15 || 1, min = 0, w = 100;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * w, v === null || v === undefined ? null : h - ((v - min) / (max - min)) * h]);
  const line = pts.filter((p) => p[1] !== null).map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join("");
  const id = "sp" + ++gid;
  const first = pts.find((p) => p[1] !== null), last = [...pts].reverse().find((p) => p[1] !== null);
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" width="100%" height="${h}">
    <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".28"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
    <path d="${line}L${last[0]},${h}L${first[0]},${h}Z" fill="url(#${id})"/>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`;
}

/** Multi-series area/line chart with hover tooltip. series: [{name,color,values:[{x,y}],fill}] */
export function lineChart(el, series, { height = 200, yFmt = (v) => v, xFmt = (v) => v, yMax, unit = "", minY = 0 } = {}) {
  const draw = () => {
    const W = Math.max(240, el.clientWidth || 600), H = height, pl = 44, pr = 10, pt = 10, pb = 24;
    const all = series.flatMap((s) => s.values.filter((p) => p.y !== null && p.y !== undefined));
    const xs = series.flatMap((s) => s.values.map((p) => p.x));
    if (!xs.length) { el.innerHTML = ""; return; }
    const x0 = Math.min(...xs), x1 = Math.max(...xs) || x0 + 1;
    const top = nice(yMax ?? Math.max(1, ...all.map((p) => p.y)) * 1.1);
    const X = (x) => pl + ((x - x0) / (x1 - x0 || 1)) * (W - pl - pr), Y = (y) => pt + (1 - (y - minY) / (top - minY)) * (H - pt - pb);
    let g = "";
    for (let i = 0; i <= 4; i++) {
      const v = minY + ((top - minY) * i) / 4, y = Y(v);
      g += `<line x1="${pl}" x2="${W - pr}" y1="${y}" y2="${y}" stroke="var(--chart-grid)"/>
        <text x="${pl - 8}" y="${y + 4}" text-anchor="end" font-size="10.5" fill="var(--text-3)">${esc(yFmt(v))}</text>`;
    }
    const ticks = Math.min(6, Math.floor(W / 110));
    for (let i = 0; i <= ticks; i++) {
      const x = x0 + ((x1 - x0) * i) / ticks;
      g += `<text x="${X(x)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === ticks ? "end" : "middle"}" font-size="10.5" fill="var(--text-3)">${esc(xFmt(x))}</text>`;
    }
    let paths = "";
    series.forEach((s) => {
      const id = "lc" + ++gid;
      const segs = []; let cur = [];
      s.values.forEach((p) => { if (p.y === null || p.y === undefined) { if (cur.length) segs.push(cur); cur = []; } else cur.push(p); });
      if (cur.length) segs.push(cur);
      paths += `<defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${s.color}" stop-opacity=".25"/><stop offset="1" stop-color="${s.color}" stop-opacity="0"/></linearGradient></defs>`;
      segs.forEach((seg) => {
        const d = seg.map((p, i) => `${i ? "L" : "M"}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join("");
        if (s.fill !== false && seg.length > 1) paths += `<path d="${d}L${X(seg.at(-1).x)},${Y(minY)}L${X(seg[0].x)},${Y(minY)}Z" fill="url(#${id})"/>`;
        paths += seg.length > 1 ? `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`
          : `<circle cx="${X(seg[0].x)}" cy="${Y(seg[0].y)}" r="2.5" fill="${s.color}"/>`;
      });
    });
    el.innerHTML = `<div class="chart"><svg viewBox="0 0 ${W} ${H}" height="${H}">${g}${paths}
      <line class="hl" x1="0" x2="0" y1="${pt}" y2="${H - pb}" stroke="var(--border-2)" stroke-dasharray="3 3" opacity="0"/>
      ${series.map((s, i) => `<circle class="hd" data-i="${i}" r="4.5" fill="var(--panel)" stroke="${s.color}" stroke-width="2.5" opacity="0"/>`).join("")}
      <rect x="${pl}" y="0" width="${W - pl - pr}" height="${H}" fill="transparent" class="hit"/></svg><div class="tip"></div></div>`;
    const svg = el.querySelector("svg"), tip = el.querySelector(".tip"), hl = el.querySelector(".hl");
    const hit = el.querySelector(".hit");
    hit.addEventListener("pointermove", (e) => {
      const rect = svg.getBoundingClientRect(), mx = ((e.clientX - rect.left) / rect.width) * W;
      const xv = x0 + ((mx - pl) / (W - pl - pr)) * (x1 - x0);
      let lines = [], px = null;
      series.forEach((s, i) => {
        let best = null;
        for (const p of s.values) if (p.y !== null && p.y !== undefined && (!best || Math.abs(p.x - xv) < Math.abs(best.x - xv))) best = p;
        const dot = el.querySelector(`.hd[data-i="${i}"]`);
        if (best) { dot.setAttribute("cx", X(best.x)); dot.setAttribute("cy", Y(best.y)); dot.setAttribute("opacity", 1); px = X(best.x);
          lines.push(`<span style="color:${s.color}">●</span> ${esc(s.name || "")} ${esc(yFmt(best.y))}${unit}`); }
      });
      if (px === null) return;
      hl.setAttribute("x1", px); hl.setAttribute("x2", px); hl.setAttribute("opacity", 1);
      tip.innerHTML = `${esc(xFmt(xv, true))}<br>${lines.join("<br>")}`;
      tip.style.left = (px / W) * 100 + "%"; tip.style.top = "18px"; tip.classList.add("show");
    });
    hit.addEventListener("pointerleave", () => { tip.classList.remove("show"); hl.setAttribute("opacity", 0); el.querySelectorAll(".hd").forEach((d) => d.setAttribute("opacity", 0)); });
  };
  draw();
  if (el._ro) el._ro.disconnect();
  el._ro = new ResizeObserver(() => { if (Math.abs((el._w || 0) - el.clientWidth) > 4) { el._w = el.clientWidth; draw(); } });
  el._w = el.clientWidth;
  el._ro.observe(el);
}

/** Grouped vertical bars. groups: [{label, values:[{v,color}]}] */
export function barChart(el, groups, { height = 200, yFmt = (v) => v } = {}) {
  const W = Math.max(240, el.clientWidth || 600), H = height, pl = 44, pb = 24, pt = 8;
  const top = nice(Math.max(1, ...groups.flatMap((g) => g.values.map((v) => v.v || 0))) * 1.1);
  const Y = (v) => pt + (1 - v / top) * (H - pt - pb);
  const gw = (W - pl - 6) / Math.max(1, groups.length);
  let s = "";
  for (let i = 0; i <= 4; i++) { const v = (top * i) / 4; s += `<line x1="${pl}" x2="${W}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--chart-grid)"/><text x="${pl - 8}" y="${Y(v) + 4}" text-anchor="end" font-size="10.5" fill="var(--text-3)">${esc(yFmt(v))}</text>`; }
  groups.forEach((g, gi) => {
    const n = g.values.length, bw = Math.min(16, (gw - 8) / n);
    g.values.forEach((v, vi) => {
      const x = pl + gi * gw + (gw - bw * n - 3 * (n - 1)) / 2 + vi * (bw + 3), y = Y(v.v || 0);
      s += `<rect x="${x}" y="${y}" width="${bw}" height="${Math.max(0, H - pb - y)}" rx="${Math.min(4, bw / 2)}" fill="${v.color}"><title>${esc(g.label)} · ${esc(yFmt(v.v))}</title></rect>`;
    });
    if (groups.length <= 14 || gi % Math.ceil(groups.length / 10) === 0)
      s += `<text x="${pl + gi * gw + gw / 2}" y="${H - 6}" text-anchor="middle" font-size="10.5" fill="var(--text-3)">${esc(g.label)}</text>`;
  });
  el.innerHTML = `<div class="chart"><svg viewBox="0 0 ${W} ${H}" height="${H}">${s}</svg></div>`;
}
