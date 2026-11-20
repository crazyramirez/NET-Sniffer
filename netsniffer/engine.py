"""Discovery engine: full & light scans, enrichment, history merge, intruder detection."""
from __future__ import annotations

import asyncio
import logging
import platform
import re
import time

import psutil

from . import demo
from .db import Database
from .hub import Hub
from .net import arp, names, oui
from .net.classify import classify, display_name
from .net.interfaces import network_info, public_info, scan_targets
from .net.ports import scan_host
from .net.utils import is_local_ip, is_randomized_mac
from .notify import Notifier

log = logging.getLogger("netsniffer.engine")

CLASSIFY_PORTS = [22, 23, 80, 135, 139, 443, 445, 515, 548, 554, 631, 1400, 3389, 5000, 5555, 7000, 8008, 8009,
                  8080, 8554, 9100, 32400, 34567, 37777, 62078]
LOCAL_SUFFIX = re.compile(r"\.(lan|home|local|localdomain|fritz\.box|home\.arpa|router|domain|station|gateway|"
                          r"totolink|tplinkdeco)\.?$", re.I)


class Engine:
    def __init__(self, db: Database, hub: Hub, notifier: Notifier) -> None:
        self.db, self.hub, self.notifier = db, hub, notifier
        self.mdns = names.MdnsBrowser()
        self.net: dict = {}
        self.ssdp: dict[str, dict] = {}
        self.wsd: dict[str, dict] = {}
        self.lock = asyncio.Lock()
        self.state: dict = {"running": False, "kind": None, "phase": None, "progress": 0, "last": None,
                            "last_full": None, "found": 0, "duration": None}

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if demo.ENABLED:
            demo.seed(self.db)
        await self.mdns.start()
        await self.refresh_network(public=False)

    async def stop(self) -> None:
        await self.mdns.stop()

    async def refresh_network(self, public: bool = True) -> dict:
        if demo.ENABLED:
            self.net = dict(demo.NETWORK)
            await self.hub.broadcast("network", self.net)
            return self.net
        info = await asyncio.to_thread(network_info)
        if public and self.db.get_setting("public_ip_lookup", True):
            info["public"] = await public_info()
        elif self.net.get("public"):
            info["public"] = self.net["public"]
        gw_ssdp = self.ssdp.get(info.get("gateway") or "")
        info["upnp_igd"] = bool(gw_ssdp and gw_ssdp.get("igd"))
        info["router_model"] = (gw_ssdp or {}).get("model")
        info["router_vendor"] = (gw_ssdp or {}).get("manufacturer")
        self.net = info
        await self.hub.broadcast("network", info)
        return info

    async def _phase(self, phase: str, pct: int) -> None:
        self.state.update(phase=phase, progress=pct)
        await self.hub.broadcast("scan", self.state)

    # ------------------------------------------------------------------ scanning
    async def scan(self, full: bool = True, deep: bool = False) -> dict:
        if demo.ENABLED:
            return await self._demo_scan()
        if self.lock.locked():
            return self.state
        async with self.lock:
            t0 = time.time()
            self.state.update(running=True, kind="full" if full else "light", phase="network", progress=2)
            await self.hub.broadcast("scan", self.state)
            try:
                if full or not self.net:
                    await self.refresh_network(public=full)
                targets = scan_targets(self.net)
                if not targets:
                    raise RuntimeError("no_network")
                await self._phase("discover", 8)
                side = []
                if full:
                    side = [asyncio.create_task(names.ssdp_discover()), asyncio.create_task(names.wsd_discover())]
                await arp.poke(targets)
                await self._phase("discover", 22)
                await asyncio.sleep(1.8)
                await arp.poke(targets)
                await self._phase("discover", 38)
                await asyncio.sleep(1.6 if full else 1.2)
                table = await arp.neighbor_table()
                await self._phase("identify", 50)
                target_set = set(targets)
                alive = {ip: e["mac"] for ip, e in table.items()
                         if ip in target_set and arp.is_fresh(e) and is_local_ip(ip)}
                if self.net.get("ip") and self.net.get("mac"):
                    alive[self.net["ip"]] = self.net["mac"]
                if side:
                    ssdp, wsd = await asyncio.gather(*side, return_exceptions=True)
                    if isinstance(ssdp, dict):
                        self.ssdp.update(ssdp)
                    if isinstance(wsd, dict):
                        self.wsd.update(wsd)
                    gw = self.ssdp.get(self.net.get("gateway") or "")
                    if gw:
                        self.net.update(upnp_igd=bool(gw.get("igd")), router_model=gw.get("model"),
                                        router_vendor=gw.get("manufacturer"))
                existing = {d["id"]: d for d in self.db.devices()}
                enrich_ips = list(alive) if full else [ip for ip, mac in alive.items() if mac not in existing]
                enrich = await self._enrich(enrich_ips, existing, alive, deep) if enrich_ips else {}
                await self._phase("merge", 92)
                summary = await self._merge(alive, enrich, existing)
                self.state.update(last=time.time(), found=len(alive), duration=round(time.time() - t0, 1))
                if full:
                    self.state["last_full"] = time.time()
                return summary
            except Exception as exc:  # noqa: BLE001
                log.exception("scan failed")
                await self.hub.broadcast("scan_error", {"error": str(exc)})
                return {"error": str(exc)}
            finally:
                self.state.update(running=False, phase=None, progress=100)
                await self.hub.broadcast("scan", self.state)
                await self.hub.broadcast("devices", self.devices())

    async def _enrich(self, ips: list[str], existing: dict, alive: dict, deep: bool) -> dict[str, dict]:
        nb, md, rd = await asyncio.gather(names.netbios_names(ips), names.mdns_hostnames(ips),
                                          names.reverse_dns(ips))
        await self._phase("identify", 70)
        now = time.time()
        need_ports = []
        for ip in ips:
            old = existing.get(alive.get(ip) or "")
            last = ((old or {}).get("extra") or {}).get("hint_ts", 0)
            if deep or not old or now - last > 7 * 86400:
                need_ports.append(ip)
        hints: dict[str, list[int]] = {}
        sem = asyncio.Semaphore(24)

        async def light(ip: str) -> None:
            async with sem:
                try:
                    res = await scan_host(ip, ports=CLASSIFY_PORTS, timeout=0.7, banners=False, concurrency=25)
                    hints[ip] = [p["port"] for p in res]
                except Exception:  # noqa: BLE001
                    pass

        await asyncio.gather(*(light(ip) for ip in need_ports))
        out = {}
        for ip in ips:
            out[ip] = {"netbios": nb.get(ip), "mdns_host": md.get(ip), "rdns": rd.get(ip),
                       "mdns": self.mdns.get(ip), "ssdp": self.ssdp.get(ip), "wsd": self.wsd.get(ip),
                       "open": hints.get(ip)}
        return out

    def _self_info(self) -> dict:
        battery = None
        try:
            battery = psutil.sensors_battery()
        except Exception:  # noqa: BLE001
            pass
        osname = {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}.get(platform.system(), platform.system())
        return {"type": "laptop" if battery else "desktop", "os": f"{osname} {platform.release()}".strip()}

    async def _merge(self, alive: dict[str, str], enrich: dict[str, dict], existing: dict) -> dict:
        now = time.time()
        baseline = bool(existing)
        gw_ip = self.net.get("gateway")
        gw_mac = alive.get(gw_ip or "")
        gw_prefix = gw_mac[:8] if gw_mac else None
        seen: set[str] = set()
        new, online, offline = [], [], []
        ip_changes: list[tuple[dict, str]] = []

        for ip, mac in alive.items():
            did = mac or f"ip:{ip}"
            seen.add(did)
            old = existing.get(did)
            rec = dict(old) if old else {
                "id": did, "mac": mac, "first_seen": now, "name": None, "trusted": False, "favorite": False,
                "blocked": False, "notes": "", "services": [], "ports": [], "extra": {}, "type_locked": False,
            }
            extra = dict(rec.get("extra") or {})
            extra["miss"] = 0
            rec.update(ip=ip, last_seen=now, online=True, randomized=is_randomized_mac(mac),
                       is_gateway=(ip == gw_ip), is_self=(ip == self.net.get("ip")))
            rec["vendor"] = oui.lookup(mac) or rec.get("vendor")
            e = enrich.get(ip)
            if e:
                mdns = e.get("mdns") or {}
                ssdp = e.get("ssdp") or {}
                wsd = e.get("wsd") or {}
                if e.get("netbios"):
                    extra["netbios"] = e["netbios"]["name"]
                    extra["workgroup"] = e["netbios"].get("workgroup")
                if e.get("rdns"):
                    extra["rdns"] = LOCAL_SUFFIX.sub("", e["rdns"].rstrip("."))
                if mdns:
                    extra["mdns_name"] = names.mdns_friendly(mdns)
                    extra["mdns_host"] = mdns.get("host")
                    extra["mdns_txt"] = mdns.get("txt")
                    rec["services"] = sorted(set(rec.get("services") or []) | set(mdns.get("services", [])))
                if e.get("mdns_host"):
                    extra["mdns_host"] = e["mdns_host"]
                if ssdp:
                    extra["ssdp"] = {k: ssdp.get(k) for k in ("friendly_name", "manufacturer", "model",
                                                               "model_number", "device_type", "server",
                                                               "presentation_url", "igd")}
                if wsd:
                    extra["wsd"] = wsd
                if e.get("open") is not None:
                    extra["open_hint"] = e["open"]
                    extra["hint_ts"] = now
                rec["hostname"] = extra.get("mdns_host") or extra.get("netbios") or extra.get("rdns") \
                    or rec.get("hostname")
                rec["model"] = names.mdns_model(mdns) or (ssdp.get("model") if ssdp else None) or rec.get("model")
                if not rec["vendor"] and ssdp.get("manufacturer"):
                    rec["vendor"] = ssdp["manufacturer"]
            rec["extra"] = extra
            if rec["is_self"]:
                si = self._self_info()
                rec["hostname"] = self.net.get("hostname") or rec.get("hostname")
                rec["os"] = si["os"]
                if not rec.get("type_locked"):
                    rec["type"] = si["type"]
            elif not rec.get("type_locked"):
                ctx = {**rec, "mdns_name": extra.get("mdns_name"), "netbios": extra.get("netbios"),
                       "ssdp_name": (extra.get("ssdp") or {}).get("friendly_name"),
                       "ssdp_type": (extra.get("ssdp") or {}).get("device_type"),
                       "wsd": extra.get("wsd"), "open_hint": extra.get("open_hint")}
                rec["type"], guess = classify(ctx, gw_prefix)
                rec["os"] = guess or rec.get("os")
            self.db.upsert_device(rec)
            if not old:
                new.append(rec)
            elif not old.get("online"):
                online.append(rec)
            if old and old.get("ip") != ip and old.get("ip"):
                ip_changes.append((rec, old["ip"]))

        for did, old in existing.items():
            if not old.get("online") or did in seen or old.get("is_self"):
                continue
            extra = dict(old.get("extra") or {})
            extra["miss"] = extra.get("miss", 0) + 1
            if extra["miss"] >= 2 or now - (old.get("last_seen") or 0) > 900:
                self.db.update_device(did, online=False, extra=extra)
                offline.append(old)
            else:
                self.db.update_device(did, extra=extra)

        for rec in new:
            nm = self._name(rec)
            params = {"name": nm, "ip": rec["ip"], "mac": rec.get("mac"), "vendor": rec.get("vendor") or ""}
            if baseline:
                await self.notifier.alert("device_new", "warning", rec["id"], params)
                if rec.get("type") == "camera":
                    await self.notifier.alert("camera_detected", "warning", rec["id"], params)
            else:
                self.db.add_event("device_first_seen", "info", rec["id"], params)
        s = self.db.settings()
        for rec in online:
            params = {"name": self._name(rec), "ip": rec["ip"], "vendor": rec.get("vendor") or ""}
            if not rec.get("trusted") and not rec.get("is_self"):
                # a device you haven't recognised is back on the network
                await self.notifier.alert("device_unknown_online", "warning", rec["id"], params)
            else:
                wanted = s.get("notify_device_online") or (rec.get("favorite") and s.get("notify_favorites", True))
                await self.notifier.alert("device_online", "info", rec["id"], params, notify=bool(wanted))
        for rec in offline:
            wanted = s.get("notify_device_offline") or (rec.get("favorite") and s.get("notify_favorites", True))
            await self.notifier.alert("device_offline", "info", rec["id"],
                                      {"name": self._name(rec), "ip": rec.get("ip")}, notify=bool(wanted))
        for rec, old_ip in ip_changes:
            await self.notifier.alert("device_ip_changed", "info", rec["id"],
                                      {"old": old_ip, "new": rec["ip"], "name": self._name(rec)})
        return {"found": len(alive), "new": len(new), "online": len(online), "offline": len(offline)}

    @staticmethod
    def _name(rec: dict) -> str:
        ex = rec.get("extra") or {}
        return display_name({**rec, "mdns_name": ex.get("mdns_name"), "netbios": ex.get("netbios"),
                             "ssdp_name": (ex.get("ssdp") or {}).get("friendly_name")})

    # ------------------------------------------------------------------ views
    def devices(self) -> list[dict]:
        out = []
        for d in self.db.devices():
            out.append(self.present(d))
        return out

    def present(self, d: dict) -> dict:
        ex = d.get("extra") or {}
        d = dict(d)
        d["display_name"] = self._name(d)
        d["mdns_name"] = ex.get("mdns_name")
        d["netbios"] = ex.get("netbios")
        d["ssdp"] = ex.get("ssdp")
        d["open_hint"] = ex.get("open_hint") or []
        d.pop("extra", None)
        d["extra"] = {k: ex.get(k) for k in ("workgroup", "rdns", "mdns_host", "mdns_txt", "wsd", "hint_ts")
                      if ex.get(k)}
        return d

    # ------------------------------------------------------------------ background loops
    async def _demo_scan(self) -> dict:
        now = time.time()
        for d in self.db.devices():
            if d["online"]:
                self.db.update_device(d["id"], last_seen=now)
        found = sum(1 for d in self.db.devices() if d["online"])
        self.state.update(running=False, last=now, last_full=now, found=found, duration=6.2, progress=100)
        await self.hub.broadcast("scan", self.state)
        await self.hub.broadcast("devices", self.devices())
        return {"found": found, "new": 0, "online": 0, "offline": 0}

    async def auto_loop(self) -> None:
        await asyncio.sleep(2)
        await self.scan(full=True)
        last_full = time.time()
        while True:
            await asyncio.sleep(30)
            s = self.db.settings()
            interval = max(1, int(s.get("scan_interval_min") or 15)) * 60
            if s.get("auto_scan", True) and time.time() - last_full >= interval:
                await self.scan(full=True)
                last_full = time.time()
            elif s.get("watcher", True) and time.time() - (self.state.get("last") or 0) >= 90:
                await self.scan(full=False)
