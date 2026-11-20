"""Alert dispatch: persisted event → WebSocket → desktop notification → optional push channels.

Every kind of notification can be switched on/off in Settings, plus a master switch, quiet hours
and sound. Events are always recorded in the in-app alert history regardless of these switches.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from pathlib import Path
from typing import Callable

import httpx

from . import __app_name__, i18n
from .config import PACKAGE_DIR
from .db import Database
from .hub import Hub

log = logging.getLogger("netsniffer.notify")

# event kind -> settings toggle that enables notifications for it (None = always when master is on)
NOTIFY_TOGGLES = {
    "device_new": "notify_new_device",
    "device_unknown_online": "notify_unknown_online",
    "device_ip_changed": "notify_ip_change",
    "internet_down": "notify_internet",
    "internet_up": "notify_internet",
    "gateway_down": "notify_internet",
    "security_issues": "notify_security",
    "camera_detected": "notify_camera",
}


def in_quiet_hours(s: dict, now: dt.datetime | None = None) -> bool:
    if not s.get("notify_quiet"):
        return False
    now = now or dt.datetime.now()
    try:
        sh, sm = map(int, str(s.get("notify_quiet_start") or "23:00").split(":"))
        eh, em = map(int, str(s.get("notify_quiet_end") or "07:00").split(":"))
    except ValueError:
        return False
    cur, start, end = now.hour * 60 + now.minute, sh * 60 + sm, eh * 60 + em
    return start <= cur < end if start <= end else (cur >= start or cur < end)


class Notifier:
    def __init__(self, db: Database, hub: Hub, desktop: bool = True) -> None:
        self.db, self.hub = db, hub
        self.desktop_enabled = desktop
        self._desktop = None
        self.on_click: Callable[[], None] | None = None

    async def _send_desktop(self, title: str, body: str, sound: bool = True) -> None:
        if not self.desktop_enabled:
            return
        try:
            from desktop_notifier import DesktopNotifier, Icon
            if self._desktop is None:
                icon = PACKAGE_DIR / "web" / "icon.png"
                self._desktop = DesktopNotifier(app_name=__app_name__,
                                                app_icon=Icon(path=Path(icon)) if icon.exists() else None)
            kwargs = {"title": title, "message": body, "sound": None}
            if sound:
                from desktop_notifier import DEFAULT_SOUND
                kwargs["sound"] = DEFAULT_SOUND
            if self.on_click:
                kwargs["on_clicked"] = self.on_click
            await asyncio.wait_for(self._desktop.send(**kwargs), 8)
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

    def wants(self, kind: str, s: dict | None = None) -> bool:
        """Whether a notification of this kind should leave the app (desktop / push)."""
        s = s or self.db.settings()
        if not s.get("notify_enabled", True) or in_quiet_hours(s):
            return False
        toggle = NOTIFY_TOGGLES.get(kind, "missing")
        return toggle != "missing" and (toggle is None or bool(s.get(toggle, True)))

    async def alert(self, kind: str, severity: str = "info", device_id: str | None = None,
                    params: dict | None = None, store: bool = True, notify: bool | None = None) -> dict:
        """Record + broadcast an event. `notify=None` decides from the per-kind toggle; a bool forces the
        decision (the master switch and quiet hours still apply)."""
        params = params or {}
        ev = self.db.add_event(kind, severity, device_id, params) if store else \
            {"id": None, "kind": kind, "severity": severity, "device_id": device_id, "params": params}
        await self.hub.broadcast("event", ev)
        s = self.db.settings()
        if notify is None:
            if not self.wants(kind, s):
                return ev
        elif not notify or not s.get("notify_enabled", True) or in_quiet_hours(s):
            return ev
        await self.dispatch(s, f"notify.{kind}", params, severity)
        return ev

    async def dispatch(self, s: dict, key: str, params: dict, severity: str = "info", push: bool = True) -> None:
        lang = i18n.resolve(s.get("language"))
        title = i18n.tr(lang, f"{key}.title", **params)
        body = i18n.tr(lang, f"{key}.body", **params)
        tasks = []
        if s.get("notify_desktop", True):
            tasks.append(self._send_desktop(title, body, bool(s.get("notify_sound", True))))
        if push:
            tasks.append(self._send_push(s, title, body, severity))
        asyncio.get_running_loop().create_task(asyncio.gather(*tasks, return_exceptions=True))

    async def hint_background(self) -> None:
        """One-time hint when the window is closed while monitoring continues in the tray."""
        s = self.db.settings()
        if s.get("notify_enabled", True):
            await self.dispatch(s, "notify.background", {}, push=False)

    async def test(self) -> None:
        s = self.db.settings()
        lang = i18n.resolve(s.get("language"))
        title, body = i18n.tr(lang, "notify.test.title"), i18n.tr(lang, "notify.test.body")
        await asyncio.gather(self._send_desktop(title, body, bool(s.get("notify_sound", True))),
                             self._send_push(s, title, body, "info"), return_exceptions=True)
