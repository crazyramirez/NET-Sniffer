// Internationalisation: JSON dictionaries + Intl formatters (dates, numbers, relative time).
export const LANGS = { es: "Español", en: "English", fr: "Français", de: "Deutsch", it: "Italiano", zh: "中文", ja: "日本語" };
let dict = {}, fallback = {}, lang = "en", plural = new Intl.PluralRules("en");
const cache = {};

async function fetchDict(l) {
  if (!cache[l]) cache[l] = fetch(`/locales/${l}.json`, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  return cache[l];
}
export function detectLang(setting, osLang) {
  if (setting && setting !== "auto" && LANGS[setting]) return setting;
  for (const tag of navigator.languages || [navigator.language]) {
    const base = String(tag || "").toLowerCase().split("-")[0];
    if (LANGS[base]) return base;
  }
  return LANGS[osLang] ? osLang : "en";
}
export async function setLang(l) {
  lang = LANGS[l] ? l : "en";
  [dict, fallback] = await Promise.all([fetchDict(lang), fetchDict("en")]);
  plural = new Intl.PluralRules(lang);
  document.documentElement.lang = lang === "zh" ? "zh-CN" : lang;
}
export const getLang = () => lang;

function get(obj, key) {
  let cur = obj;
  for (const p of key.split(".")) { if (cur == null || typeof cur !== "object") return undefined; cur = cur[p]; }
  return typeof cur === "string" ? cur : undefined;
}
export function t(key, params = {}) {
  let s;
  if (typeof params.count === "number") {
    const cat = plural.select(params.count);
    s = get(dict, `${key}_${cat}`) ?? get(dict, `${key}_other`) ?? get(fallback, `${key}_${cat}`) ?? get(fallback, `${key}_other`);
  }
  s = s ?? get(dict, key) ?? get(fallback, key);
  if (s === undefined) return key.split(".").pop().replace(/_/g, " ");
  return s.replace(/\{(\w+)\}/g, (m, k) => (params[k] !== undefined && params[k] !== null ? String(params[k]) : m));
}
export const has = (key) => get(dict, key) !== undefined || get(fallback, key) !== undefined;

const nf = (o) => new Intl.NumberFormat(lang, o);
export const fmt = {
  num: (n, d = 0) => (n === null || n === undefined || Number.isNaN(n) ? "—" : nf({ maximumFractionDigits: d, minimumFractionDigits: d }).format(n)),
  mbps: (n) => (n === null || n === undefined ? "—" : nf({ maximumFractionDigits: n < 10 ? 2 : n < 100 ? 1 : 0 }).format(n)),
  pct: (n, d = 1) => (n === null || n === undefined ? "—" : nf({ maximumFractionDigits: d }).format(n) + " %"),
  date: (ts) => (ts ? new Intl.DateTimeFormat(lang, { dateStyle: "medium", timeStyle: "short" }).format(new Date(ts * 1000)) : "—"),
  day: (ts) => new Intl.DateTimeFormat(lang, { day: "numeric", month: "short" }).format(new Date(ts * 1000)),
  time: (ts) => new Intl.DateTimeFormat(lang, { hour: "2-digit", minute: "2-digit" }).format(new Date(ts * 1000)),
  ago(ts) {
    if (!ts) return "—";
    const diff = ts - Date.now() / 1000, rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
    const a = Math.abs(diff);
    if (a < 45) return t("common.just_now");
    if (a < 3600) return rtf.format(Math.round(diff / 60), "minute");
    if (a < 86400) return rtf.format(Math.round(diff / 3600), "hour");
    if (a < 86400 * 30) return rtf.format(Math.round(diff / 86400), "day");
    return fmt.date(ts);
  },
  dur(sec) {
    if (sec === null || sec === undefined) return "—";
    sec = Math.round(sec);
    const u = (v, unit) => nf({ style: "unit", unit, unitDisplay: "narrow" }).format(v);
    if (sec < 60) return u(sec, "second");
    if (sec < 3600) return `${u(Math.floor(sec / 60), "minute")} ${u(sec % 60, "second")}`;
    if (sec < 86400) return `${u(Math.floor(sec / 3600), "hour")} ${u(Math.floor((sec % 3600) / 60), "minute")}`;
    return `${u(Math.floor(sec / 86400), "day")} ${u(Math.floor((sec % 86400) / 3600), "hour")}`;
  },
  weekday: (i) => new Intl.DateTimeFormat(lang, { weekday: "short" }).format(new Date(2024, 0, 1 + i)), // 2024-01-01 = Monday
};
