"""Alert dispatch: persisted event → WebSocket → desktop notification → optional push channels."""
from __future__ import annotations

import asyncio
import logging

import httpx

from . import __app_name__, i18n, licensing
from .db import Database
from .hub import Hub

log = logging.getLogger("netsniffer.notify")

# event kind -> settings toggle that enables notifications for it
NOTIFY_TOGGLES = {
    "device_new": "notify_new_device",
    "device_offline": "notify_device_offline",
    "device_online": "notify_device_offline",
    "internet_down": "notify_internet",
    "internet_up": "notify_internet",
    "gateway_down": "notify_internet",
    "security_issues": "notify_security",
    "camera_detected": "notify_security",
    "update_installed": None,
}


class Notifier:
    def __init__(self, db: Database, hub: Hub, desktop: bool = True) -> None:
        self.db, self.hub = db, hub
        self.desktop_enabled = desktop
        self._desktop = None

    async def _send_desktop(self, title: str, body: str) -> None:
        if not self.desktop_enabled:
            return
        try:
            if self._desktop is None:
                from desktop_notifier import DesktopNotifier
                self._desktop = DesktopNotifier(app_name=__app_name__)
            await asyncio.wait_for(self._desktop.send(title=title, message=body), 8)
        except Exception as exc:  # noqa: BLE001 - notifications are best effort
            log.debug("desktop notification failed: %s", exc)

    async def _send_push(self, s: dict, title: str, body: str, severity: str) -> None:
        async with httpx.AsyncClient(timeout=8) as c:
            jobs = []
            if s.get("notify_ntfy_url"):
                # JSON publishing keeps UTF-8 titles intact (ES/FR/DE/ZH/JA)
                url = httpx.URL(s["notify_ntfy_url"])
                prio = {"critical": 5, "warning": 4}.get(severity, 3)
                jobs.append(c.post(str(url.copy_with(path="/")),
                                   json={"topic": url.path.strip("/"), "title": title, "message": body,
                                         "priority": prio, "tags": ["satellite"]}))
            if s.get("notify_telegram_token") and s.get("notify_telegram_chat"):
                jobs.append(c.post(f"https://api.telegram.org/bot{s['notify_telegram_token']}/sendMessage",
                                   json={"chat_id": s["notify_telegram_chat"], "text": f"{title}\n{body}"}))
            if s.get("notify_webhook_url"):
                jobs.append(c.post(s["notify_webhook_url"], json={"app": __app_name__, "title": title,
                                                                    "body": body, "severity": severity}))
            for res in await asyncio.gather(*jobs, return_exceptions=True):
                if isinstance(res, Exception):
                    log.debug("push failed: %s", res)

    async def alert(self, kind: str, severity: str = "info", device_id: str | None = None,
                    params: dict | None = None, store: bool = True, notify: bool = True) -> dict:
        params = params or {}
        ev = self.db.add_event(kind, severity, device_id, params) if store else \
            {"id": None, "kind": kind, "severity": severity, "device_id": device_id, "params": params}
        await self.hub.broadcast("event", ev)
        if not notify:
            return ev
        s = self.db.settings()
        toggle = NOTIFY_TOGGLES.get(kind, "missing")
        if toggle == "missing" or (toggle and not s.get(toggle, True)):
            return ev
        if not licensing.has(s, "notifications"):
            return ev
        lang = i18n.resolve(s.get("language"))
        title = i18n.tr(lang, f"notify.{kind}.title", **params)
        body = i18n.tr(lang, f"notify.{kind}.body", **params)
        tasks = []
        if s.get("notify_desktop", True):
            tasks.append(self._send_desktop(title, body))
        tasks.append(self._send_push(s, title, body, severity))
        asyncio.get_running_loop().create_task(asyncio.gather(*tasks, return_exceptions=True))
        return ev

    async def test(self) -> None:
        s = self.db.settings()
        lang = i18n.resolve(s.get("language"))
        title, body = i18n.tr(lang, "notify.test.title"), i18n.tr(lang, "notify.test.body")
        await asyncio.gather(self._send_desktop(title, body), self._send_push(s, title, body, "info"),
                             return_exceptions=True)
