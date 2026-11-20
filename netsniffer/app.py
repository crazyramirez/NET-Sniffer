"""HTTP/WebSocket API and static UI."""
from __future__ import annotations

import asyncio
import contextlib
import csv
import html
import io
import logging
import re
import socket
import time
from typing import Any

import uvicorn
from fastapi import Body, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __app_name__, __version__, i18n, licensing
from .audit import Auditor
from .auth import COOKIE, RateLimiter, hash_password, new_token, verify_password
from .blocking import BlockError, BlockManager
from .config import DEFAULT_SETTINGS, SECRET_SETTINGS, SUPPORTED_LANGUAGES, WEB_DIR
from .db import Database
from .engine import Engine
from .hub import Hub
from .monitor import Monitor
from .net.ports import PROFILES, scan_host
from .net.utils import NotLocalError, arun_cmd, is_local_ip, platform_name, tcp_probe
from .notify import Notifier
from .speedtest import SpeedTest
from .updater import Updater, cleanup_previous

log = logging.getLogger("netsniffer.app")
MASK = "••••••••"


class Context:
    def __init__(self, headless: bool = False) -> None:
        self.headless = headless
        self.db = Database()
        s = self.db.settings()
        if not s.get("first_run"):
            self.db.set_settings({"first_run": time.time()})
        self.hub = Hub()
        self.notifier = Notifier(self.db, self.hub, desktop=not headless)
        self.engine = Engine(self.db, self.hub, self.notifier)
        self.monitor = Monitor(self.db, self.hub, self.notifier, self.engine)
        self.speed = SpeedTest()
        self.auditor = Auditor(self.db, self.hub, self.notifier, self.engine)
        self.blocker = BlockManager(self.db, self.hub, self.notifier)
        self.updater = Updater(self.db, self.hub)
        self.updater.headless = headless
        self.launch_token = new_token()
        self.setup_token = new_token()[:12]
        self.limiter = RateLimiter()
        self.tasks: list[asyncio.Task] = []
        self.remote_server: uvicorn.Server | None = None
        self.remote_task: asyncio.Task | None = None
        self.app: FastAPI | None = None
        self.port = 0
        self.speed_last: dict = {}
        self.audit_last: dict | None = None

    # ------------------------------------------------------------------ remote listener (desktop mode)
    async def apply_remote(self) -> None:
        if self.headless:
            return
        s = self.db.settings()
        want = bool(s.get("remote_enabled")) and licensing.has(s, "remote") and bool(s.get("remote_password"))
        port = int(s.get("remote_port") or 8765)
        if self.remote_server:
            if want and self.remote_server.config.port == port:
                return
            self.remote_server.should_exit = True
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.remote_task, 5)
            self.remote_server = self.remote_task = None
        if want and self.app:
            cfg = uvicorn.Config(self.app, host="0.0.0.0", port=port, lifespan="off", log_config=None,
                                 access_log=False, ws="websockets-sansio")
            self.remote_server = uvicorn.Server(cfg)
            self.remote_task = asyncio.create_task(self.remote_server.serve())

    def remote_status(self) -> dict:
        s = self.db.settings()
        ip = self.engine.net.get("ip")
        port = self.port if self.headless else int(s.get("remote_port") or 8765)
        running = self.headless or bool(self.remote_server and self.remote_server.started)
        return {"enabled": bool(s.get("remote_enabled")) or self.headless, "running": running,
                "password_set": bool(s.get("remote_password")), "port": port,
                "urls": [f"http://{ip}:{port}"] if ip else [], "hostname": socket.gethostname(),
                "allowed": licensing.has(s, "remote") or self.headless}

    # ------------------------------------------------------------------ lifecycle
    async def startup(self) -> None:
        cleanup_previous()
        await self.engine.start()
        spawn = lambda coro: self.tasks.append(asyncio.create_task(coro))  # noqa: E731
        spawn(self.engine.auto_loop())
        spawn(self.monitor.loop())
        spawn(self.monitor.bandwidth_loop())
        spawn(self.blocker.loop())
        spawn(self.updater.loop())
        spawn(self._housekeeping())
        audit = self.db.get_setting("last_audit")
        self.audit_last = audit if isinstance(audit, dict) else None
        await self.apply_remote()

    async def shutdown(self) -> None:
        for t in self.tasks:
            t.cancel()
        if self.remote_server:
            self.remote_server.should_exit = True
        await self.engine.stop()

    async def _housekeeping(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = time.time()
            for r in self.db.rules():
                if r["name"].startswith("__pause__") and float(r.get("paused_until") or 0) < now:
                    self.db.delete_rule(r["id"])
                    await self.blocker.reconcile()

    # ------------------------------------------------------------------ helpers
    def public_settings(self) -> dict:
        s = self.db.settings()
        out = {k: s.get(k) for k in DEFAULT_SETTINGS}
        for k in SECRET_SETTINGS:
            out[k] = MASK if s.get(k) else ""
        return out

    def snapshot(self) -> dict:
        s = self.db.settings()
        devices = self.engine.devices()
        return {
            "app": {"name": __app_name__, "version": __version__, "platform": platform_name(),
                    "headless": self.headless, "os_language": i18n.os_language(), "languages": SUPPORTED_LANGUAGES},
            "network": self.engine.net, "scan": self.engine.state, "devices": devices,
            "monitor": self.monitor.state, "license": licensing.status(s), "settings": self.public_settings(),
            "update": self.updater.state, "unread": self.db.unread_count(), "blocking": self.blocker.status(),
            "remote": self.remote_status(), "speed_last": (self.db.speedtests(1) or [None])[0],
            "audit_last": self.audit_last, "bandwidth": self.monitor.bandwidth,
        }


def err(status: int, key: str, **params) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": key, "params": params})


def create_app(ctx: Context) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        await ctx.startup()
        yield
        await ctx.shutdown()

    app = FastAPI(title=__app_name__, version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None)
    ctx.app = app

    # ------------------------------------------------------------------ auth
    def session_ok(request: Request | WebSocket) -> bool:
        tok = request.cookies.get(COOKIE)
        return bool(tok) and ctx.db.session_valid(tok)

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "?"

    async def auth_dep(request: Request) -> None:
        if not session_ok(request):
            raise err(401, "unauthorized")

    def feature(name: str):
        async def dep() -> None:
            if not licensing.has(ctx.db.settings(), name):
                raise err(402, "pro_required", feature=name)
        return Depends(dep)

    def set_cookie(resp: Response, request: Request) -> Response:
        tok = new_token()
        ctx.db.add_session(tok, client_ip(request))
        resp.set_cookie(COOKIE, tok, httponly=True, samesite="strict", max_age=30 * 86400, path="/")
        return resp

    @app.exception_handler(NotLocalError)
    async def _not_local(_: Request, exc: NotLocalError):
        return JSONResponse({"detail": {"error": "not_local", "params": {"ip": str(exc)}}}, status_code=403)

    @app.get("/launch")
    async def launch(request: Request, token: str = ""):
        if token and token == ctx.launch_token:
            return set_cookie(RedirectResponse("/", status_code=303), request)
        return RedirectResponse("/", status_code=303)

    @app.get("/api/auth/status")
    async def auth_status(request: Request):
        s = ctx.db.settings()
        return {"authenticated": session_ok(request), "password_set": bool(s.get("remote_password")),
                "setup_required": ctx.headless and not s.get("remote_password"), "app": __app_name__,
                "version": __version__}

    @app.post("/api/auth/setup")
    async def auth_setup(request: Request, body: dict = Body(...)):
        s = ctx.db.settings()
        if s.get("remote_password"):
            raise err(409, "already_configured")
        if body.get("token") != ctx.setup_token:
            ctx.limiter.fail(client_ip(request))
            raise err(403, "bad_setup_token")
        pw = str(body.get("password") or "")
        if len(pw) < 8:
            raise err(400, "password_short")
        ctx.db.set_settings({"remote_password": hash_password(pw)})
        return set_cookie(JSONResponse({"ok": True}), request)

    @app.post("/api/auth/login")
    async def auth_login(request: Request, body: dict = Body(...)):
        ip = client_ip(request)
        if ctx.limiter.blocked(ip):
            raise err(429, "too_many_attempts")
        await asyncio.sleep(0.4)
        if not verify_password(str(body.get("password") or ""), ctx.db.get_setting("remote_password")):
            ctx.limiter.fail(ip)
            raise err(401, "bad_password")
        ctx.limiter.reset(ip)
        return set_cookie(JSONResponse({"ok": True}), request)

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request):
        tok = request.cookies.get(COOKIE)
        if tok:
            ctx.db.delete_session(tok)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    A = [Depends(auth_dep)]

    # ------------------------------------------------------------------ state
    @app.get("/api/state", dependencies=A)
    async def state():
        return ctx.snapshot()

    @app.get("/api/network", dependencies=A)
    async def network(refresh: bool = False):
        return await ctx.engine.refresh_network(public=True) if refresh else ctx.engine.net

    # ------------------------------------------------------------------ scan & devices
    @app.post("/api/scan", dependencies=A)
    async def scan(body: dict = Body(default={})):
        if ctx.engine.lock.locked():
            return {"started": False, "state": ctx.engine.state}
        asyncio.create_task(ctx.engine.scan(full=True, deep=bool(body.get("deep"))))
        return {"started": True}

    @app.get("/api/devices", dependencies=A)
    async def devices():
        return ctx.engine.devices()

    def get_dev(device_id: str) -> dict:
        d = ctx.db.device(device_id)
        if not d:
            raise err(404, "device_not_found")
        return d

    @app.get("/api/devices/{device_id}", dependencies=A)
    async def device(device_id: str):
        d = ctx.engine.present(get_dev(device_id))
        d["events"] = ctx.db.events(60, device_id=device_id)
        d["pause_until"] = max((r["paused_until"] for r in ctx.db.rules()
                                if r["name"] == f"__pause__{device_id}"), default=0)
        d["rules"] = [r["id"] for r in ctx.db.rules() if device_id in r["devices"] and not r["name"].startswith("__")]
        return d

    @app.patch("/api/devices/{device_id}", dependencies=A)
    async def patch_device(device_id: str, body: dict = Body(...)):
        get_dev(device_id)
        allowed = {"name", "type", "trusted", "notes", "favorite"}
        fields = {k: v for k, v in body.items() if k in allowed}
        if "name" in fields:
            fields["name"] = (str(fields["name"]).strip()[:64]) or None
        if "notes" in fields:
            fields["notes"] = str(fields["notes"])[:2000]
        if "type" in fields:
            fields["type_locked"] = True
        ctx.db.update_device(device_id, **fields)
        d = ctx.engine.present(ctx.db.device(device_id))
        await ctx.hub.broadcast("device", d)
        return d

    @app.post("/api/devices/trust-all", dependencies=A)
    async def trust_all():
        for d in ctx.db.devices():
            if not d["trusted"]:
                ctx.db.update_device(d["id"], trusted=True)
        await ctx.hub.broadcast("devices", ctx.engine.devices())
        return {"ok": True}

    @app.delete("/api/devices/{device_id}", dependencies=A)
    async def delete_device(device_id: str):
        ctx.db.delete_device(device_id)
        await ctx.hub.broadcast("devices", ctx.engine.devices())
        return {"ok": True}

    @app.post("/api/devices/{device_id}/ports", dependencies=A)
    async def device_ports(device_id: str, body: dict = Body(default={})):
        d = get_dev(device_id)
        profile = body.get("profile", "quick")
        if profile not in PROFILES:
            raise err(400, "bad_profile")
        if profile != "quick" and not licensing.has(ctx.db.settings(), "full_ports"):
            raise err(402, "pro_required", feature="full_ports")

        async def progress(done: int, total: int) -> None:
            await ctx.hub.broadcast("ports_progress", {"device_id": device_id, "done": done, "total": total})

        ports = await scan_host(d["ip"], profile=profile, progress=progress)
        ctx.db.update_device(device_id, ports=ports, ports_scanned=time.time())
        res = ctx.engine.present(ctx.db.device(device_id))
        await ctx.hub.broadcast("device", res)
        return res

    @app.post("/api/devices/{device_id}/ping", dependencies=A)
    async def device_ping(device_id: str):
        d = get_dev(device_id)
        ip = d["ip"]
        if not is_local_ip(ip):
            raise NotLocalError(ip)
        plat = platform_name()
        cmd = ["ping", "-n", "5", "-w", "1000", ip] if plat == "windows" else \
            ["ping", "-c", "5", "-W", "1000" if plat == "macos" else "1", ip]
        out = await arun_cmd(cmd, timeout=12)
        times = [float(x.replace(",", ".")) for x in re.findall(r"[=<]\s*([\d.,]+)\s*ms", out)]
        method = "icmp"
        if not times:
            method = "tcp"
            for port in (80, 443, 22, 445, 62078, 53, 7000):
                ok, rtt = await tcp_probe(ip, port, 1.0)
                if ok and rtt is not None:
                    for _ in range(4):
                        ok2, rtt2 = await tcp_probe(ip, port, 1.0)
                        if ok2 and rtt2 is not None:
                            times.append(rtt2)
                    times.append(rtt)
                    break
        sent = 5
        return {"method": method, "sent": sent, "received": min(sent, len(times)),
                "min": round(min(times), 1) if times else None, "avg": round(sum(times) / len(times), 1)
                if times else None, "max": round(max(times), 1) if times else None}

    @app.post("/api/devices/{device_id}/wol", dependencies=A)
    async def device_wol(device_id: str):
        d = get_dev(device_id)
        mac = d.get("mac")
        if not mac:
            raise err(400, "no_mac")
        packet = b"\xff" * 6 + bytes.fromhex(mac.replace(":", "")) * 16
        targets = {"255.255.255.255"}
        cidr = ctx.engine.net.get("cidr")
        if cidr:
            import ipaddress
            targets.add(str(ipaddress.ip_network(cidr).broadcast_address))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for t in targets:
                for port in (9, 7):
                    with contextlib.suppress(OSError):
                        s.sendto(packet, (t, port))
        return {"ok": True}

    @app.post("/api/devices/{device_id}/block", dependencies=[*A, feature("blocking")])
    async def device_block(device_id: str, body: dict = Body(default={})):
        d = get_dev(device_id)
        if d["is_self"] or d["is_gateway"]:
            raise err(400, "cannot_block_self")
        if not ctx.blocker.backend():
            raise err(409, "block_not_configured")
        blocked = bool(body.get("blocked", True))
        ctx.db.update_device(device_id, blocked=blocked)
        await ctx.blocker.reconcile(force=True)
        if ctx.blocker.last_error:
            ctx.db.update_device(device_id, blocked=d["blocked"])
            raise err(502, "block_failed", detail=ctx.blocker.last_error)
        name = ctx.engine.present(ctx.db.device(device_id))["display_name"]
        await ctx.notifier.alert("device_blocked" if blocked else "device_unblocked", "info", device_id,
                                 {"name": name}, notify=False)
        res = ctx.engine.present(ctx.db.device(device_id))
        await ctx.hub.broadcast("device", res)
        return res

    @app.post("/api/devices/{device_id}/pause", dependencies=[*A, feature("parental")])
    async def device_pause(device_id: str, body: dict = Body(default={})):
        get_dev(device_id)
        if not ctx.blocker.backend():
            raise err(409, "block_not_configured")
        minutes = int(body.get("minutes") or 0)
        name = f"__pause__{device_id}"
        existing = next((r for r in ctx.db.rules() if r["name"] == name), None)
        if minutes <= 0:
            if existing:
                ctx.db.delete_rule(existing["id"])
        else:
            ctx.db.save_rule({"id": existing["id"] if existing else None, "name": name, "devices": [device_id],
                              "schedule": [], "enabled": True, "paused_until": time.time() + minutes * 60})
        await ctx.blocker.reconcile(force=True)
        if ctx.blocker.last_error:
            raise err(502, "block_failed", detail=ctx.blocker.last_error)
        return {"ok": True, "until": time.time() + minutes * 60 if minutes > 0 else 0}

    # ------------------------------------------------------------------ events / alerts
    @app.get("/api/events", dependencies=A)
    async def events(limit: int = 200):
        return {"events": ctx.db.events(min(limit, 1000)), "unread": ctx.db.unread_count()}

    @app.post("/api/events/read", dependencies=A)
    async def events_read(body: dict = Body(default={})):
        ctx.db.mark_read(body.get("id"))
        await ctx.hub.broadcast("unread", ctx.db.unread_count())
        return {"unread": ctx.db.unread_count()}

    @app.delete("/api/events", dependencies=A)
    async def events_clear():
        ctx.db.clear_events()
        await ctx.hub.broadcast("unread", 0)
        return {"ok": True}

    # ------------------------------------------------------------------ speed test
    @app.post("/api/speedtest", dependencies=A)
    async def speedtest():
        if ctx.speed.running:
            raise err(409, "speedtest_running")

        async def progress(p: dict) -> None:
            ctx.speed_last = p
            await ctx.hub.broadcast("speed", p)

        async def job() -> None:
            try:
                res = await ctx.speed.run(progress)
                ctx.db.add_speedtest(res)
            except Exception as exc:  # noqa: BLE001
                await ctx.hub.broadcast("speed", {"phase": "error", "error": str(exc)})

        asyncio.create_task(job())
        return {"started": True}

    @app.get("/api/speedtest/history", dependencies=A)
    async def speed_history():
        lim = 200 if licensing.has(ctx.db.settings(), "history") else 10
        return {"history": ctx.db.speedtests(lim), "running": ctx.speed.running, "last": ctx.speed_last}

    # ------------------------------------------------------------------ monitor
    @app.get("/api/monitor", dependencies=A)
    async def monitor(hours: int = 24):
        return ctx.monitor.summary(max(1, min(hours, 24 * 30)))

    # ------------------------------------------------------------------ security
    @app.post("/api/audit", dependencies=[*A, feature("audit")])
    async def audit():
        if ctx.auditor.running:
            raise err(409, "audit_running")

        async def job() -> None:
            try:
                ctx.audit_last = await ctx.auditor.run()
            except Exception as exc:  # noqa: BLE001
                log.exception("audit")
                await ctx.hub.broadcast("audit", {"phase": "error", "error": str(exc)})

        asyncio.create_task(job())
        return {"started": True}

    @app.get("/api/audit", dependencies=A)
    async def audit_get():
        return {"report": ctx.audit_last, "running": ctx.auditor.running}

    @app.post("/api/cameras", dependencies=[*A, feature("cameras")])
    async def cameras():
        return await ctx.auditor.cameras()

    # ------------------------------------------------------------------ parental
    @app.get("/api/parental", dependencies=A)
    async def parental():
        from .blocking import rule_active
        rules = [dict(r, active=rule_active(r)) for r in ctx.db.rules() if not r["name"].startswith("__")]
        return {"rules": rules, "blocking": ctx.blocker.status()}

    def clean_rule(body: dict) -> dict:
        sched = []
        for slot in body.get("schedule") or []:
            if re.fullmatch(r"\d{2}:\d{2}", str(slot.get("start", ""))) and \
                    re.fullmatch(r"\d{2}:\d{2}", str(slot.get("end", ""))):
                sched.append({"days": [int(x) for x in slot.get("days", []) if 0 <= int(x) <= 6],
                              "start": slot["start"], "end": slot["end"]})
        name = str(body.get("name") or "").strip()[:60] or "Rule"
        if name.startswith("__"):
            name = name.lstrip("_")
        return {"name": name, "devices": [str(x) for x in body.get("devices") or []][:100], "schedule": sched,
                "enabled": bool(body.get("enabled", True)), "paused_until": float(body.get("paused_until") or 0)}

    @app.post("/api/parental", dependencies=[*A, feature("parental")])
    async def rule_create(body: dict = Body(...)):
        rid = ctx.db.save_rule(clean_rule(body))
        await ctx.blocker.reconcile()
        return {"id": rid}

    @app.put("/api/parental/{rule_id}", dependencies=[*A, feature("parental")])
    async def rule_update(rule_id: int, body: dict = Body(...)):
        ctx.db.save_rule({**clean_rule(body), "id": rule_id})
        await ctx.blocker.reconcile()
        return {"id": rule_id}

    @app.delete("/api/parental/{rule_id}", dependencies=A)
    async def rule_delete(rule_id: int):
        ctx.db.delete_rule(rule_id)
        await ctx.blocker.reconcile()
        return {"ok": True}

    @app.post("/api/blocking/test", dependencies=[*A, feature("blocking")])
    async def blocking_test():
        b = ctx.blocker.backend()
        if not b:
            raise err(409, "block_not_configured")
        try:
            return {"ok": True, "info": await b.test()}
        except BlockError as exc:
            raise err(502, "block_failed", detail=str(exc)) from exc

    # ------------------------------------------------------------------ settings
    @app.get("/api/settings", dependencies=A)
    async def settings_get():
        return {"settings": ctx.public_settings(), "remote": ctx.remote_status()}

    @app.put("/api/settings", dependencies=A)
    async def settings_put(body: dict = Body(...)):
        current = ctx.db.settings()
        upd: dict[str, Any] = {}
        for k, v in body.items():
            if k not in DEFAULT_SETTINGS:
                continue
            if k in SECRET_SETTINGS and v == MASK:
                continue
            default = DEFAULT_SETTINGS[k]
            if isinstance(default, bool):
                v = bool(v)
            elif isinstance(default, int):
                try:
                    v = int(v)
                except (TypeError, ValueError):
                    continue
            elif isinstance(default, str):
                v = str(v)[:500]
            upd[k] = v
        if "language" in upd and upd["language"] not in ["auto", *SUPPORTED_LANGUAGES]:
            upd.pop("language")
        if "theme" in upd and upd["theme"] not in ("system", "light", "dark"):
            upd.pop("theme")
        if "scan_interval_min" in upd:
            upd["scan_interval_min"] = max(1, min(240, upd["scan_interval_min"]))
        if "remote_port" in upd:
            upd["remote_port"] = max(1024, min(65535, upd["remote_port"]))
        if "block_backend" in upd and upd["block_backend"] not in ("none", "ssh", "fritz", "local"):
            upd.pop("block_backend")
        if upd.get("block_host", current.get("block_host")) != current.get("block_host"):
            upd["block_hostkey"] = ""  # new router → pin its key again
        for url_key in ("notify_ntfy_url", "notify_webhook_url"):
            if upd.get(url_key) and not re.match(r"^https?://", upd[url_key]):
                raise err(400, "bad_url")
        ctx.db.set_settings(upd)
        if {"remote_enabled", "remote_port"} & set(upd):
            await ctx.apply_remote()
        if any(k.startswith("block_") for k in upd):
            ctx.blocker.applied = {}
            asyncio.create_task(ctx.blocker.reconcile(force=True))
        res = {"settings": ctx.public_settings(), "remote": ctx.remote_status()}
        await ctx.hub.broadcast("settings", res)
        return res

    @app.post("/api/settings/remote-password", dependencies=A)
    async def remote_password(body: dict = Body(...)):
        pw = str(body.get("password") or "")
        if len(pw) < 8:
            raise err(400, "password_short")
        ctx.db.set_settings({"remote_password": hash_password(pw)})
        await ctx.apply_remote()
        return {"remote": ctx.remote_status()}

    @app.get("/api/remote/qr.svg", dependencies=A)
    async def remote_qr(dark: bool = False):
        import segno
        urls = ctx.remote_status()["urls"]
        if not urls:
            raise err(404, "no_network")
        buf = io.BytesIO()
        segno.make(urls[0], error="m").save(buf, kind="svg", scale=6, border=2,
                                             dark="#E9EDF7" if dark else "#0E1525", light=None)
        return Response(buf.getvalue(), media_type="image/svg+xml")

    @app.post("/api/settings/notify-test", dependencies=[*A, feature("notifications")])
    async def notify_test():
        await ctx.notifier.test()
        return {"ok": True}

    # ------------------------------------------------------------------ license
    @app.get("/api/license", dependencies=A)
    async def license_get():
        return licensing.status(ctx.db.settings())

    @app.post("/api/license", dependencies=A)
    async def license_set(body: dict = Body(...)):
        key = str(body.get("key") or "").strip()
        info = licensing.verify_key(key)
        if not info:
            raise err(400, "license_invalid")
        if info.get("expired"):
            raise err(400, "license_expired")
        ctx.db.set_settings({"license_key": key})
        st = licensing.status(ctx.db.settings())
        await ctx.hub.broadcast("license", st)
        return st

    @app.delete("/api/license", dependencies=A)
    async def license_del():
        ctx.db.set_settings({"license_key": ""})
        st = licensing.status(ctx.db.settings())
        await ctx.hub.broadcast("license", st)
        return st

    # ------------------------------------------------------------------ updates
    @app.get("/api/update", dependencies=A)
    async def update_get():
        return ctx.updater.state

    @app.post("/api/update/check", dependencies=A)
    async def update_check():
        return await ctx.updater.check()

    @app.post("/api/update/apply", dependencies=A)
    async def update_apply():
        ok = await ctx.updater.apply_now()
        if not ok:
            raise err(409, "update_not_ready", detail=ctx.updater.state.get("error") or "")
        return {"ok": True}

    # ------------------------------------------------------------------ export
    @app.get("/api/export/devices.csv", dependencies=[*A, feature("export")])
    async def export_csv():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["name", "ip", "mac", "vendor", "model", "type", "os", "online", "trusted", "first_seen",
                    "last_seen", "open_ports"])
        for d in ctx.engine.devices():
            w.writerow([d["display_name"], d["ip"], d.get("mac"), d.get("vendor"), d.get("model"), d.get("type"),
                        d.get("os"), d["online"], d["trusted"],
                        time.strftime("%Y-%m-%d %H:%M", time.localtime(d["first_seen"] or 0)),
                        time.strftime("%Y-%m-%d %H:%M", time.localtime(d["last_seen"] or 0)),
                        " ".join(str(p["port"]) for p in d.get("ports") or [])])
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="netsniffer-devices.csv"'})

    @app.get("/api/export/report.html", dependencies=[*A, feature("export")])
    async def export_report(lang: str = "auto"):
        lg = lang if lang in SUPPORTED_LANGUAGES else i18n.resolve(ctx.db.get_setting("language"))
        t = lambda k, **p: html.escape(i18n.tr(lg, k, **p))  # noqa: E731
        net = ctx.engine.net
        rep = ctx.audit_last or {}
        rows = "".join(
            f"<tr><td>{html.escape(d['display_name'])}</td><td>{d['ip']}</td><td>{d.get('mac') or ''}</td>"
            f"<td>{html.escape(d.get('vendor') or '')}</td><td>{t('types.' + (d.get('type') or 'unknown'))}</td>"
            f"<td>{'●' if d['online'] else '○'}</td><td>{'✓' if d['trusted'] else '—'}</td></tr>"
            for d in ctx.engine.devices())
        finds = "".join(
            f"<li class='{f['severity']}'><b>{t('severity.' + f['severity'])}</b> — "
            f"{t('audit.f.' + f['id'] + '.title', **{k: str(v) for k, v in (f.get('params') or {}).items()})}</li>"
            for f in rep.get("findings", []))
        doc = f"""<!doctype html><html lang="{lg}"><meta charset="utf-8"><title>{__app_name__} — {t('report.title')}</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;margin:40px;color:#0f172a}}h1{{margin:0}}table{{border-collapse:collapse;width:100%;margin-top:12px}}
td,th{{border-bottom:1px solid #e2e8f0;padding:6px 8px;text-align:left}}th{{background:#f1f5f9}}.critical{{color:#b91c1c}}.high{{color:#c2410c}}
.medium{{color:#a16207}}.low{{color:#0369a1}}.score{{font-size:40px;font-weight:700}}</style>
<h1>{__app_name__} · {t('report.title')}</h1><p>{time.strftime('%Y-%m-%d %H:%M')} · {html.escape(net.get('cidr') or '')} ·
{html.escape((net.get('wifi') or {}).get('ssid') or '')}</p>
<h2>{t('security.score')}</h2><div class="score">{rep.get('score', '—')}</div><ul>{finds}</ul>
<h2>{t('nav.devices')}</h2><table><tr><th>{t('device.name')}</th><th>IP</th><th>MAC</th><th>{t('device.vendor')}</th>
<th>{t('device.type')}</th><th>{t('device.online')}</th><th>{t('device.trusted')}</th></tr>{rows}</table></html>"""
        return HTMLResponse(doc, headers={"Content-Disposition": 'attachment; filename="netsniffer-report.html"'})

    # ------------------------------------------------------------------ websocket
    @app.websocket("/api/ws")
    async def ws(socket_: WebSocket):
        if not session_ok(socket_):
            await socket_.close(code=4401)
            return
        await ctx.hub.connect(socket_)
        try:
            while True:
                msg = await socket_.receive_text()
                if msg == "ping":
                    await socket_.send_text('{"type":"pong"}')
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            pass
        finally:
            ctx.hub.disconnect(socket_)

    # ------------------------------------------------------------------ static UI
    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        path = request.url.path
        if not path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        return resp

    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    return app
