"""Demo mode (NETSNIFFER_DEMO=1): fictional network used for screenshots and presentations.

Uses documentation address ranges (RFC 5737 public IP) and made-up names, so nothing from the
machine's real network appears. Real scanning is disabled while demo mode is on.
"""
from __future__ import annotations

import math
import os
import random
import time

ENABLED = os.environ.get("NETSNIFFER_DEMO") == "1"

NETWORK = {
    "hostname": "STUDIO-PC", "interface": "Wi-Fi", "ip": "192.168.1.24", "mac": "3c:22:fb:4a:10:24",
    "netmask": "255.255.255.0", "cidr": "192.168.1.0/24", "prefix": 24, "hosts": 254, "gateway": "192.168.1.1",
    "dns": ["192.168.1.1"], "connection": "wifi", "upnp_igd": True, "router_model": "RT-AX86U", "router_vendor": "ASUS",
    "wifi": {"ssid": "Home-WiFi-6", "bssid": "04:42:1a:9c:00:11", "band": "5 GHz", "channel": 44, "radio": "802.11ax",
             "auth": "WPA3", "cipher": "CCMP", "signal": 88, "rssi": -51, "rx_rate": 1201.0, "tx_rate": 1081.0},
    "public": {"ip": "203.0.113.24", "isp": "FiberNet Hogar", "asn": 64500, "city": "Madrid", "region": "Madrid",
               "country": "ES", "colo": "Madrid"},
}

H = 3600
D = 86400
# (mac, ip, name, vendor, model, type, os, trusted, favorite, online, first_seen_ago, last_seen_ago, ports, extra)
DEVICES = [
    ("04:42:1a:9c:00:10", "192.168.1.1", "ASUS RT-AX86U", "ASUS", "RT-AX86U", "router", "Router OS", 1, 0, 1, 210 * D, 0, [53, 80, 443, 1900], {}),
    ("04:42:1a:9c:22:31", "192.168.1.2", "Mesh node · Upstairs", "ASUS", "RP-AX58", "mesh", None, 1, 0, 1, 180 * D, 0, [80, 443], {}),
    ("3c:22:fb:4a:10:24", "192.168.1.24", "STUDIO-PC", "Intel", None, "laptop", "Windows 11", 1, 0, 1, 210 * D, 0, [135, 139, 445], {"self": 1}),
    ("f0:18:98:5e:7a:01", "192.168.1.31", "MacBook Pro", "Apple", "Mac15,7", "laptop", "macOS", 1, 1, 1, 150 * D, 0, [22, 5000, 7000], {}),
    ("9a:41:c3:10:5b:77", "192.168.1.32", "iPhone 15 Pro", None, "iPhone16,1", "phone", "iOS", 1, 1, 1, 120 * D, 0, [62078], {"rand": 1}),
    ("d6:2f:81:44:90:12", "192.168.1.33", "Galaxy S24", None, None, "phone", "Android", 1, 0, 1, 90 * D, 0, [], {"rand": 1}),
    ("ae:88:20:7c:31:05", "192.168.1.34", "iPad Air", None, "iPad13,16", "tablet", "iPadOS", 1, 0, 1, 140 * D, 0, [62078], {"rand": 1}),
    ("70:2a:d5:6e:10:4c", "192.168.1.40", "Living Room TV", "Samsung", "QE55Q80C", "tv", "Tizen", 1, 0, 1, 200 * D, 0, [8001, 8002, 9197], {}),
    ("d4:f5:47:21:aa:90", "192.168.1.41", "Chromecast", "Google", "Chromecast with Google TV", "streamer", None, 1, 0, 1, 160 * D, 0, [8008, 8009], {}),
    ("48:a6:b8:33:0f:12", "192.168.1.42", "Sonos One · Kitchen", "Sonos", "One SL", "speaker", None, 1, 0, 1, 170 * D, 0, [1400], {}),
    ("ec:71:db:5a:4e:20", "192.168.1.50", "Front Door Cam", "Reolink", "Video Doorbell", "camera", "Embedded Linux", 1, 0, 1, 60 * D, 0, [80, 554], {}),
    ("e8:d8:d1:7f:33:10", "192.168.1.51", "HP LaserJet M234", "HP", "LaserJet M234sdw", "printer", None, 1, 0, 1, 190 * D, 0, [80, 443, 631, 9100], {}),
    ("00:d9:d1:e2:41:6b", "192.168.1.52", "PlayStation 5", "Sony Interactive", "PS5", "console", None, 1, 0, 1, 100 * D, 0, [], {}),
    ("2c:cf:67:0c:17:95", "192.168.1.60", "pi-hole", "Raspberry Pi", "Raspberry Pi 5", "raspberry", "Linux", 1, 0, 1, 130 * D, 0, [22, 53, 80], {}),
    ("00:11:32:ab:cd:01", "192.168.1.61", "Synology DS923+", "Synology", "DS923+", "nas", "Linux", 1, 0, 1, 205 * D, 0, [22, 80, 443, 445, 5000, 5001], {}),
    ("00:17:88:6b:21:9f", "192.168.1.62", "Hue Bridge", "Philips Hue", "BSB002", "hub", None, 1, 0, 1, 195 * D, 0, [80, 443], {}),
    ("d8:1f:12:90:3b:7e", "192.168.1.77", "Smart Plug", "Tuya", None, "plug", "RTOS", 0, 0, 1, 40 * 60, 0, [6668], {}),
    ("98:b6:e9:40:12:aa", "192.168.1.55", "Nintendo Switch", "Nintendo", None, "console", None, 1, 0, 0, 80 * D, 5 * H, [], {}),
    ("f0:4f:7c:11:9e:20", "192.168.1.56", "Kindle", "Amazon", None, "tablet", None, 1, 0, 0, 220 * D, 2 * D, [], {}),
]


def _ports(lst: list[int]) -> list[dict]:
    from .net.ports import SERVICES
    return [{"port": p, "proto": "tcp", "service": SERVICES.get(p, ("unknown", "low", "other"))[0],
             "risk": SERVICES.get(p, ("unknown", "low", "other"))[1], "category": "", "banner": None} for p in lst]


def seed(db) -> None:
    if db.q("SELECT COUNT(*) c FROM devices")[0]["c"]:
        return
    rnd = random.Random(7)
    now = time.time()
    for (mac, ip, name, vendor, model, typ, os_, trusted, fav, online, first, last, ports, ex) in DEVICES:
        db.upsert_device({
            "id": mac, "mac": mac, "ip": ip, "hostname": name, "name": name, "vendor": vendor, "model": model,
            "type": typ, "os": os_, "first_seen": now - first, "last_seen": now - last, "online": online,
            "trusted": trusted, "favorite": fav, "blocked": False, "is_gateway": ip == "192.168.1.1",
            "is_self": bool(ex.get("self")), "randomized": bool(ex.get("rand")), "services": [],
            "ports": _ports(ports), "ports_scanned": now - 3 * H if ports else None, "notes": "",
            "type_locked": True, "extra": {"open_hint": ports},
        })
    ev = [
        (now - 40 * 60, "device_new", "warning", "d8:1f:12:90:3b:7e", {"name": "Smart Plug", "ip": "192.168.1.77", "mac": "d8:1f:12:90:3b:7e", "vendor": "Tuya"}),
        (now - 2 * H, "device_online", "info", "f0:18:98:5e:7a:01", {"name": "MacBook Pro", "ip": "192.168.1.31"}),
        (now - 5 * H, "device_offline", "info", "98:b6:e9:40:12:aa", {"name": "Nintendo Switch", "ip": "192.168.1.55"}),
        (now - 9 * H, "internet_up", "info", None, {"duration": "4m 12s", "seconds": 252}),
        (now - 9 * H - 252, "internet_down", "critical", None, {"scope": "internet"}),
        (now - 20 * H, "security_issues", "warning", None, {"count": 1, "score": 86}),
        (now - 26 * H, "device_ip_changed", "info", "9a:41:c3:10:5b:77", {"old": "192.168.1.38", "new": "192.168.1.32", "name": "iPhone 15 Pro"}),
        (now - 30 * H, "device_online", "info", "9a:41:c3:10:5b:77", {"name": "iPhone 15 Pro", "ip": "192.168.1.32"}),
    ]
    for ts, kind, sev, did, params in ev:
        db.add_event(kind, sev, did, params, ts=ts)
    for i in range(12):
        db.add_speedtest({"ts": now - (11 - i) * D - rnd.randint(0, 6) * H, "ping": round(rnd.uniform(7, 13), 1),
                          "jitter": round(rnd.uniform(0.6, 2.4), 1), "download": round(rnd.uniform(860, 948), 1),
                          "upload": round(rnd.uniform(560, 640), 1), "isp": NETWORK["public"]["isp"],
                          "server": "Cloudflare · Madrid", "ip": NETWORK["public"]["ip"]})
    out_start = now - 9 * H - 252
    rows = []
    for i in range(24 * 60):
        ts = now - 24 * H + i * 60
        down = out_start <= ts < out_start + 252
        lat = None if down else round(11 + 3 * math.sin(i / 90) + rnd.uniform(-1.5, 2.5) + (18 if 1150 < i < 1170 else 0), 1)
        rows.append((ts, lat, int(not down), 1, int(not down)))
    with db._lock:
        db.conn.executemany("INSERT INTO samples VALUES(?,?,?,?,?)", rows)
    oid = db.open_outage(out_start, "internet")
    db.close_outage(oid, out_start + 252)
    db.set_settings({"onboarded": True, "last_audit": {
        "ts": now - 20 * H, "score": 86, "devices": 17, "profile": "common", "passed": ["wifi_wpa3", "no_risky_services"],
        "counts": {"critical": 0, "high": 0, "medium": 2, "low": 2, "info": 1},
        "findings": [
            {"id": "upnp_enabled", "severity": "medium", "params": {"router": "RT-AX86U"}},
            {"id": "port_rtsp", "severity": "medium", "device_id": "ec:71:db:5a:4e:20", "params": {"device": "Front Door Cam", "ip": "192.168.1.50", "port": 554, "service": "RTSP", "banner": ""}},
            {"id": "untrusted_devices", "severity": "low", "params": {"count": 1, "names": "Smart Plug"}},
            {"id": "port_smb", "severity": "low", "device_id": "00:11:32:ab:cd:01", "params": {"device": "Synology DS923+", "ip": "192.168.1.61", "port": 445, "service": "SMB", "banner": ""}},
            {"id": "cameras_present", "severity": "info", "params": {"count": 1, "names": "Front Door Cam"}},
        ]}})
