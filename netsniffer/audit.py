"""Defensive security audit of your own network: Wi-Fi config, router exposure, risky services.

Checks are passive or connect-only (is a port open, what does the service announce). Nothing is
exploited and no passwords are tried. Every finding ships with remediation guidance (UI locales).
"""
from __future__ import annotations

import asyncio
import time

from . import licensing
from .net import names
from .net.ports import SERVICES, scan_host

WEIGHTS = {"critical": 25, "high": 12, "medium": 6, "low": 2, "info": 0}
FINDING_BY_PORT = {
    23: "telnet", 2323: "telnet", 21: "ftp", 20: "ftp", 69: "tftp", 445: "smb", 139: "smb", 3389: "rdp",
    5900: "vnc", 5901: "vnc", 2375: "docker", 5555: "adb", 1883: "mqtt", 554: "rtsp", 8554: "rtsp",
    3306: "database", 5432: "database", 27017: "database", 6379: "database", 9200: "database",
    11211: "database", 1433: "database", 1521: "database", 8086: "database", 6000: "x11", 111: "rpcbind",
    1080: "proxy", 1723: "pptp", 502: "modbus", 34567: "dvr", 37777: "dvr", 4444: "suspicious",
    10000: "webmin", 7547: "tr069", 873: "rsync", 2049: "nfs", 110: "mail_plain", 143: "mail_plain",
    5985: "winrm", 135: "msrpc",
}
COMPUTER_TYPES = {"laptop", "desktop", "server", "nas", "raspberry"}
CAMERA_PORTS = [80, 443, 554, 8000, 8080, 8554, 8899, 37777, 34567, 9000, 5000]


def _severity(port: int, dev: dict) -> str:
    risk = SERVICES.get(port, ("", "low", ""))[1]
    kind = FINDING_BY_PORT.get(port)
    if kind in ("smb", "msrpc", "rdp") and dev.get("type") in COMPUTER_TYPES:
        return "low" if kind != "rdp" else "medium"
    if kind == "rtsp" and dev.get("type") == "camera":
        return "medium"
    if risk == "none":
        return "info"
    return risk


class Auditor:
    def __init__(self, db, hub, notifier, engine) -> None:
        self.db, self.hub, self.notifier, self.engine = db, hub, notifier, engine
        self.running = False

    async def run(self) -> dict:
        if self.running:
            raise RuntimeError("audit_running")
        self.running = True
        try:
            return await self._run()
        finally:
            self.running = False

    async def _run(self) -> dict:
        s = self.db.settings()
        profile = "common" if licensing.has(s, "full_ports") else "quick"
        await self.hub.broadcast("audit", {"phase": "network", "progress": 0.03})
        net = await self.engine.refresh_network(public=True)
        devices = [d for d in self.engine.devices() if d["online"]]
        findings: list[dict] = []
        passed: list[str] = []

        # --- Wi-Fi
        wifi = net.get("wifi") or {}
        auth = (wifi.get("auth") or "").upper()
        if wifi:
            if auth == "OPEN":
                findings.append({"id": "wifi_open", "severity": "critical", "params": {"ssid": wifi.get("ssid")}})
            elif auth.startswith("WEP"):
                findings.append({"id": "wifi_wep", "severity": "critical", "params": {"ssid": wifi.get("ssid")}})
            elif auth.startswith("WPA3"):
                passed.append("wifi_wpa3")
            elif auth.startswith("WPA2"):
                findings.append({"id": "wifi_wpa2", "severity": "low", "params": {"ssid": wifi.get("ssid")}})
            elif auth.startswith("WPA"):
                findings.append({"id": "wifi_wpa", "severity": "high", "params": {"ssid": wifi.get("ssid")}})
            if (wifi.get("cipher") or "").upper() == "TKIP":
                findings.append({"id": "wifi_tkip", "severity": "high", "params": {}})
        # --- Router
        if net.get("upnp_igd"):
            findings.append({"id": "upnp_enabled", "severity": "medium",
                             "params": {"router": net.get("router_model") or net.get("gateway")}})
        else:
            passed.append("upnp_disabled")

        # --- Services on every online device
        sem = asyncio.Semaphore(6)
        done = 0
        total = max(1, len(devices))

        async def scan(dev: dict) -> None:
            nonlocal done
            async with sem:
                try:
                    ports = await scan_host(dev["ip"], profile=profile, timeout=0.8)
                    self.db.update_device(dev["id"], ports=ports, ports_scanned=time.time())
                    dev["ports"] = ports
                except Exception:  # noqa: BLE001
                    pass
                done += 1
                await self.hub.broadcast("audit", {"phase": "ports", "progress": 0.08 + 0.85 * done / total,
                                                   "device": dev["display_name"]})

        await asyncio.gather(*(scan(d) for d in devices))
        gw_ip = net.get("gateway")
        for dev in devices:
            open_ports = {p["port"] for p in dev.get("ports") or []}
            for p in dev.get("ports") or []:
                kind = FINDING_BY_PORT.get(p["port"])
                if not kind:
                    continue
                sev = _severity(p["port"], dev)
                if sev == "info":
                    continue
                findings.append({"id": f"port_{kind}", "severity": sev, "device_id": dev["id"],
                                 "params": {"device": dev["display_name"], "ip": dev["ip"], "port": p["port"],
                                            "service": p["service"], "banner": p.get("banner") or ""}})
            if dev["ip"] == gw_ip and 80 in open_ports and 443 not in open_ports:
                findings.append({"id": "router_http", "severity": "low", "device_id": dev["id"],
                                 "params": {"device": dev["display_name"], "ip": dev["ip"]}})

        # --- Inventory hygiene
        untrusted = [d for d in devices if not d["trusted"] and not d["is_self"]]
        if untrusted:
            findings.append({"id": "untrusted_devices", "severity": "medium" if len(untrusted) > 2 else "low",
                             "params": {"count": len(untrusted),
                                        "names": ", ".join(d["display_name"] for d in untrusted[:6])}})
        else:
            passed.append("all_trusted")
        cams = [d for d in devices if d["type"] == "camera"]
        if cams:
            findings.append({"id": "cameras_present", "severity": "info",
                             "params": {"count": len(cams), "names": ", ".join(d["display_name"] for d in cams)}})
        if not any(f["id"].startswith("port_") and f["severity"] in ("high", "critical") for f in findings):
            passed.append("no_risky_services")

        penalty = 0
        per_id: dict[str, int] = {}
        for f in findings:
            per_id[f["id"]] = per_id.get(f["id"], 0) + 1
            # diminishing penalty for repeated findings of the same kind
            penalty += WEIGHTS[f["severity"]] / per_id[f["id"]]
        score = max(0, round(100 - penalty))
        order = list(WEIGHTS)
        findings.sort(key=lambda f: order.index(f["severity"]))
        report = {"ts": time.time(), "score": score, "findings": findings, "passed": passed,
                  "devices": len(devices), "profile": profile,
                  "counts": {k: sum(1 for f in findings if f["severity"] == k) for k in WEIGHTS}}
        self.db.set_settings({"last_audit": report})
        await self.hub.broadcast("audit", {"phase": "done", "progress": 1, "report": report})
        serious = report["counts"]["critical"] + report["counts"]["high"]
        if serious:
            await self.notifier.alert("security_issues", "critical" if report["counts"]["critical"] else "warning",
                                      None, {"count": serious, "score": score})
        return report

    async def cameras(self) -> dict:
        """Hidden-camera finder: correlates ONVIF/WS-Discovery, RTSP/DVR ports, vendor and mDNS hints."""
        wsd = await names.wsd_discover()
        self.engine.wsd.update(wsd)
        devices = [d for d in self.engine.devices() if d["online"] and not d["is_self"]]
        sem = asyncio.Semaphore(12)
        results = []

        async def check(dev: dict) -> None:
            reasons = []
            if dev["type"] == "camera":
                reasons.append("classified")
            w = wsd.get(dev["ip"]) or (dev.get("extra") or {}).get("wsd") or {}
            if w.get("camera"):
                reasons.append("onvif")
            if any("_rtsp" in s for s in dev.get("services") or []):
                reasons.append("mdns_rtsp")
            if dev["type"] in ("unknown", "iot", "camera", "mesh") or reasons:
                async with sem:
                    try:
                        ports = await scan_host(dev["ip"], ports=CAMERA_PORTS, timeout=0.8)
                    except Exception:  # noqa: BLE001
                        ports = []
                op = {p["port"] for p in ports}
                if op & {554, 8554}:
                    reasons.append("rtsp")
                if op & {37777, 34567}:
                    reasons.append("dvr")
                for p in ports:
                    b = (p.get("banner") or "").lower()
                    if any(x in b for x in ("hikvision", "dahua", "dvr", "nvr", "ipcam", "webcam", "uc-httpd",
                                            "goahead", "boa/", "app-webs", "hipcam")):
                        reasons.append("banner")
                        break
            if reasons:
                results.append({"device_id": dev["id"], "name": dev["display_name"], "ip": dev["ip"],
                                "mac": dev.get("mac"), "vendor": dev.get("vendor"), "trusted": dev["trusted"],
                                "reasons": sorted(set(reasons)),
                                "confidence": "high" if {"onvif", "rtsp", "classified"} & set(reasons)
                                and len(set(reasons)) > 1 else "medium"})

        await asyncio.gather(*(check(d) for d in devices))
        return {"ts": time.time(), "cameras": results, "scanned": len(devices)}
