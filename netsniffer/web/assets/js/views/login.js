import { api } from "../api.js";
import { t } from "../i18n.js";
import { $, html, ico } from "../ui.js";

export function renderLogin(status) {
  const setup = status.setup_required;
  $("#app").innerHTML = html`<div class="login"><div class="card">
    <div class="brand"><div class="brand-logo">${ico("logo")}</div><div><div class="brand-name">NET Sniffer</div><div class="brand-sub">${t("app.tagline")}</div></div></div>
    <h2 style="margin:0 0 4px;font-size:20px;letter-spacing:-.02em">${setup ? t("login.setup_title") : t("login.title")}</h2>
    <p class="muted" style="margin:0 0 18px;font-size:13.5px">${setup ? t("login.setup_d") : t("login.subtitle")}</p>
    <form id="lf" class="stack" style="gap:12px">
      ${setup ? html`<div class="field"><label>${t("login.setup_code")}</label><input class="input mono" id="code" autocomplete="off" required></div>` : ""}
      <div class="field"><label>${t("login.password")}</label><input class="input" type="password" id="pw" autocomplete="${setup ? "new-password" : "current-password"}" required minlength="${setup ? 8 : 1}"></div>
      ${setup ? html`<div class="field"><label>${t("login.repeat")}</label><input class="input" type="password" id="pw2" autocomplete="new-password" required></div>` : ""}
      <div id="lerr" class="badge danger hidden" style="height:auto;padding:6px 10px;border-radius:8px"></div>
      <button class="btn grad lg" type="submit">${ico(setup ? "key" : "lock")} ${setup ? t("login.create") : t("login.enter")}</button>
    </form>
    <p class="faint" style="font-size:12px;margin:16px 0 0">${t("login.footer")}</p></div></div>`;
  $("#pw").focus();
  $("#lf").onsubmit = async (e) => {
    e.preventDefault();
    const err = $("#lerr"); err.classList.add("hidden");
    try {
      if (setup) {
        if ($("#pw").value !== $("#pw2").value) throw { key: "password_mismatch" };
        await api("/auth/setup", { method: "POST", body: { token: $("#code").value.trim(), password: $("#pw").value } });
      } else {
        await api("/auth/login", { method: "POST", body: { password: $("#pw").value } });
      }
      location.reload();
    } catch (ex) {
      err.textContent = t(`errors.${ex.key || "generic"}`); err.classList.remove("hidden");
    }
  };
}
