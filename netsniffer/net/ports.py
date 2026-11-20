"""TCP service inventory for devices on your own network (connect scan + passive banner read).

Only private/local addresses are accepted. No exploitation, brute force or credential testing is
performed: each open port is identified and mapped to a risk level with remediation advice.
"""
from __future__ import annotations

import asyncio
import re
from typing import Awaitable, Callable

from .utils import require_local

# port: (service, risk, category)   risk: none|low|medium|high|critical
SERVICES: dict[int, tuple[str, str, str]] = {
    20: ("FTP-data", "medium", "file"), 21: ("FTP", "medium", "file"), 22: ("SSH", "low", "remote"),
    23: ("Telnet", "high", "remote"), 25: ("SMTP", "low", "mail"), 53: ("DNS", "none", "network"),
    67: ("DHCP", "none", "network"), 69: ("TFTP", "medium", "file"), 80: ("HTTP", "low", "web"),
    81: ("HTTP-alt", "low", "web"), 88: ("Kerberos", "none", "auth"), 110: ("POP3", "medium", "mail"),
    111: ("RPCbind", "medium", "system"), 119: ("NNTP", "low", "mail"), 123: ("NTP", "none", "network"),
    135: ("MS-RPC", "medium", "system"), 139: ("NetBIOS-SSN", "medium", "file"), 143: ("IMAP", "medium", "mail"),
    161: ("SNMP", "medium", "network"), 389: ("LDAP", "medium", "auth"), 443: ("HTTPS", "none", "web"),
    445: ("SMB", "medium", "file"), 465: ("SMTPS", "none", "mail"), 502: ("Modbus", "high", "iot"),
    515: ("LPD", "low", "print"), 548: ("AFP", "low", "file"), 554: ("RTSP", "medium", "camera"),
    587: ("SMTP-sub", "none", "mail"), 593: ("RPC-HTTP", "medium", "system"), 631: ("IPP", "low", "print"),
    636: ("LDAPS", "none", "auth"), 873: ("rsync", "medium", "file"), 902: ("VMware", "low", "system"),
    990: ("FTPS", "low", "file"), 993: ("IMAPS", "none", "mail"), 995: ("POP3S", "none", "mail"),
    1080: ("SOCKS", "high", "proxy"), 1194: ("OpenVPN", "none", "vpn"), 1400: ("Sonos", "none", "media"),
    1433: ("MSSQL", "high", "database"), 1521: ("Oracle", "high", "database"), 1723: ("PPTP", "high", "vpn"),
    1883: ("MQTT", "medium", "iot"), 1900: ("UPnP", "low", "network"), 2049: ("NFS", "medium", "file"),
    2323: ("Telnet-alt", "high", "remote"), 2375: ("Docker API", "critical", "system"),
    2376: ("Docker TLS", "low", "system"), 3000: ("HTTP-dev", "low", "web"), 3306: ("MySQL", "high", "database"),
    3389: ("RDP", "medium", "remote"), 3478: ("STUN", "none", "network"), 3702: ("WS-Discovery", "none", "network"),
    4444: ("Suspicious-4444", "high", "system"), 5000: ("UPnP/HTTP", "low", "web"), 5001: ("HTTPS-alt", "none", "web"),
    5060: ("SIP", "low", "voip"), 5222: ("XMPP", "low", "chat"), 5353: ("mDNS", "none", "network"),
    5355: ("LLMNR", "low", "network"), 5432: ("PostgreSQL", "high", "database"), 5555: ("ADB", "critical", "remote"),
    5900: ("VNC", "high", "remote"), 5901: ("VNC-1", "high", "remote"), 5985: ("WinRM", "medium", "remote"),
    6000: ("X11", "high", "remote"), 6379: ("Redis", "high", "database"), 6667: ("IRC", "medium", "chat"),
    7000: ("AirPlay", "none", "media"), 7547: ("TR-069", "medium", "network"), 8000: ("HTTP-alt", "low", "web"),
    8008: ("Cast/HTTP", "none", "media"), 8009: ("Cast", "none", "media"), 8060: ("Roku", "none", "media"),
    8080: ("HTTP-proxy", "low", "web"), 8081: ("HTTP-alt", "low", "web"), 8083: ("HTTP-alt", "low", "web"),
    8086: ("InfluxDB", "medium", "database"), 8123: ("Home Assistant", "none", "iot"),
    8291: ("MikroTik Winbox", "medium", "network"), 8443: ("HTTPS-alt", "none", "web"),
    8554: ("RTSP-alt", "medium", "camera"), 8883: ("MQTT-TLS", "none", "iot"), 8888: ("HTTP-alt", "low", "web"),
    9000: ("HTTP-alt", "low", "web"), 9001: ("Tor/HTTP", "low", "web"), 9090: ("HTTP-admin", "low", "web"),
    9100: ("JetDirect", "low", "print"), 9200: ("Elasticsearch", "high", "database"),
    9418: ("git", "low", "system"), 10000: ("Webmin", "medium", "web"), 11211: ("Memcached", "high", "database"),
    27017: ("MongoDB", "high", "database"), 32400: ("Plex", "none", "media"), 37777: ("Dahua DVR", "medium", "camera"),
    34567: ("DVR (XMeye)", "high", "camera"), 49152: ("UPnP", "low", "network"), 49153: ("UPnP", "low", "network"),
    50000: ("SAP/alt", "low", "system"), 51820: ("WireGuard", "none", "vpn"), 62078: ("iPhone Sync", "none", "mobile"),
}

PROFILES: dict[str, list[int]] = {
    "quick": [21, 22, 23, 53, 80, 135, 139, 443, 445, 554, 1883, 2375, 3306, 3389, 5000, 5555, 5900, 6379,
              7000, 8000, 8008, 8080, 8443, 8554, 9100, 27017, 32400, 34567, 37777, 62078],
    "common": sorted(SERVICES.keys()),
}
PROFILES["full"] = sorted(set(range(1, 1025)) | set(SERVICES.keys()) | {
    1025, 1026, 1027, 1110, 1234, 1337, 1701, 1755, 2000, 2001, 2082, 2083, 2086, 2087, 2222, 3001, 3128,
    3283, 3690, 4000, 4040, 4567, 4848, 5050, 5190, 5357, 5431, 5601, 5800, 6001, 6443, 6881, 7001, 7070,
    7443, 7676, 8001, 8002, 8082, 8084, 8085, 8088, 8089, 8090, 8099, 8180, 8200, 8222, 8333, 8400, 8500,
    8800, 8880, 8889, 8899, 9080, 9091, 9443, 9999, 10001, 10443, 12345, 20000, 49154, 49155, 55443, 60000})

HTTP_PORTS = {80, 81, 3000, 5000, 7000, 8000, 8008, 8060, 8080, 8081, 8083, 8088, 8123, 8888, 9000, 9090, 10000,
              32400, 49152, 49153}
BANNER_PORTS = {21, 22, 23, 25, 110, 143, 2323, 3306, 5900, 5901, 6379, 1883}


async def _banner(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, ip: str, port: int) -> str | None:
    try:
        if port in HTTP_PORTS:
            writer.write(f"HEAD / HTTP/1.0\r\nHost: {ip}\r\nUser-Agent: NETSniffer\r\n\r\n".encode())
            await writer.drain()
            data = await asyncio.wait_for(reader.read(2048), 1.5)
            text = data.decode("latin-1", "replace")
            server = re.search(r"^Server:\s*(.+)$", text, re.I | re.M)
            status = re.match(r"HTTP/\S+\s+(\d+)", text)
            if server:
                return server.group(1).strip()[:80]
            return f"HTTP {status.group(1)}" if status else None
        if port in BANNER_PORTS:
            data = await asyncio.wait_for(reader.read(256), 1.5)
            text = data.decode("latin-1", "replace")
            text = re.sub(r"[^\x20-\x7e]+", " ", text).strip()
            return text[:80] or None
    except (asyncio.TimeoutError, OSError, UnicodeError):
        return None
    return None


async def scan_host(ip: str, profile: str = "quick", ports: list[int] | None = None, timeout: float = 0.9,
                    concurrency: int = 200, progress: Callable[[int, int], Awaitable[None] | None] | None = None,
                    banners: bool = True) -> list[dict]:
    require_local(ip)
    targets = ports or PROFILES.get(profile, PROFILES["quick"])
    sem = asyncio.Semaphore(concurrency)
    found: list[dict] = []
    done = 0

    async def probe(port: int) -> None:
        nonlocal done
        async with sem:
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
            except (asyncio.TimeoutError, OSError):
                reader = writer = None
            if writer is not None:
                banner = await _banner(reader, writer, ip, port) if banners else None
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), 0.5)
                except (asyncio.TimeoutError, OSError):
                    pass
                svc, risk, cat = SERVICES.get(port, ("unknown", "low", "other"))
                found.append({"port": port, "proto": "tcp", "service": svc, "risk": risk, "category": cat,
                              "banner": banner})
            done += 1
            if progress and (done % 16 == 0 or done == len(targets)):
                r = progress(done, len(targets))
                if asyncio.iscoroutine(r):
                    await r

    await asyncio.gather(*(probe(p) for p in targets))
    return sorted(found, key=lambda x: x["port"])
