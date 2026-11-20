"""Standard, read-only discovery protocols that devices use to announce themselves on a LAN.

- NetBIOS node status (UDP 137)      → Windows / Samba computer names
- mDNS / DNS-SD (UDP 5353)           → Apple, Android, Chromecast, printers, IoT names, models, services
- SSDP / UPnP (UDP 1900)             → TVs, routers, media devices: manufacturer, model, friendly name
- WS-Discovery (UDP 3702)            → ONVIF cameras, network printers, Windows computers
- Reverse DNS (PTR via router)       → names registered by DHCP
"""
from __future__ import annotations

import asyncio
import logging
import re
import socket
import struct
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
from defusedxml import ElementTree as ET

from .utils import is_local_ip

log = logging.getLogger("netsniffer.names")
_dns_pool = ThreadPoolExecutor(max_workers=24, thread_name_prefix="rdns")


class _Collector(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.responses: list[tuple[bytes, str]] = []
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:  # type: ignore[override]
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:  # type: ignore[override]
        self.responses.append((data, addr[0]))

    def error_received(self, exc) -> None:  # type: ignore[override]
        pass


async def _udp_exchange(packets: list[tuple[bytes, tuple[str, int]]], wait: float,
                        multicast_ttl: int | None = None, repeat: int = 1) -> list[tuple[bytes, str]]:
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if multicast_ttl:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, multicast_ttl)
    sock.bind(("0.0.0.0", 0))
    transport, proto = await loop.create_datagram_endpoint(_Collector, sock=sock)
    try:
        for _ in range(repeat):
            for i, (data, addr) in enumerate(packets):
                try:
                    transport.sendto(data, addr)
                except OSError:
                    pass
                if i % 64 == 63:
                    await asyncio.sleep(0.01)
            await asyncio.sleep(wait / repeat)
    finally:
        transport.close()
    return proto.responses


# --------------------------------------------------------------------------- NetBIOS
def _nbstat_packet(tid: int) -> bytes:
    name = b"*" + b"\x00" * 15
    enc = bytes(b for c in name for b in (0x41 + (c >> 4), 0x41 + (c & 0x0F)))
    return struct.pack(">HHHHHH", tid, 0, 1, 0, 0, 0) + b"\x20" + enc + b"\x00" + struct.pack(">HH", 0x21, 1)


def _parse_nbstat(data: bytes) -> tuple[str | None, str | None]:
    try:
        num = data[56]
        off = 57
        computer = group = None
        for _ in range(num):
            raw = data[off:off + 15].decode("ascii", "replace").strip()
            suffix = data[off + 15]
            flags = struct.unpack(">H", data[off + 16:off + 18])[0]
            off += 18
            if suffix == 0x00 and not flags & 0x8000 and not computer:
                computer = raw
            elif suffix == 0x00 and flags & 0x8000 and not group:
                group = raw
        return computer, group
    except (IndexError, struct.error):
        return None, None


async def netbios_names(ips: list[str]) -> dict[str, dict]:
    packets = [(_nbstat_packet(0x4E53 + i), (ip, 137)) for i, ip in enumerate(ips)]
    out: dict[str, dict] = {}
    for data, ip in await _udp_exchange(packets, 1.6):
        name, group = _parse_nbstat(data)
        if name and ip not in out:
            out[ip] = {"name": name, "workgroup": group}
    return out


# --------------------------------------------------------------------------- mDNS unicast PTR
def _dns_name(data: bytes, off: int, depth: int = 0) -> tuple[str, int]:
    labels: list[str] = []
    jumped_end = None
    while off < len(data) and depth < 20:
        length = data[off]
        if length == 0:
            off += 1
            break
        if length & 0xC0 == 0xC0:
            ptr = struct.unpack(">H", data[off:off + 2])[0] & 0x3FFF
            if jumped_end is None:
                jumped_end = off + 2
            off = ptr
            depth += 1
            continue
        labels.append(data[off + 1:off + 1 + length].decode("utf-8", "replace"))
        off += 1 + length
    return ".".join(labels), (jumped_end if jumped_end is not None else off)


def _ptr_query(ip: str) -> bytes:
    qname = b"".join(bytes([len(p)]) + p.encode() for p in reversed(ip.split("."))) + b"\x07in-addr\x04arpa\x00"
    return struct.pack(">HHHHHH", 0x1234, 0, 1, 0, 0, 0) + qname + struct.pack(">HH", 12, 0x8001)


def _parse_ptr(data: bytes) -> str | None:
    try:
        qd, an = struct.unpack(">HH", data[4:8])
        off = 12
        for _ in range(qd):
            _, off = _dns_name(data, off)
            off += 4
        for _ in range(an):
            _, off = _dns_name(data, off)
            rtype, _, _, rdlen = struct.unpack(">HHIH", data[off:off + 10])
            off += 10
            if rtype == 12:
                return _dns_name(data, off)[0]
            off += rdlen
    except (IndexError, struct.error):
        return None
    return None


async def mdns_hostnames(ips: list[str]) -> dict[str, str]:
    packets = [(_ptr_query(ip), (ip, 5353)) for ip in ips]
    out: dict[str, str] = {}
    for data, ip in await _udp_exchange(packets, 1.6):
        name = _parse_ptr(data)
        if name and ip not in out:
            out[ip] = re.sub(r"\.local\.?$", "", name)
    return out


# --------------------------------------------------------------------------- reverse DNS
async def reverse_dns(ips: list[str], timeout: float = 2.0) -> dict[str, str]:
    loop = asyncio.get_running_loop()

    async def one(ip: str) -> tuple[str, str | None]:
        try:
            name = await asyncio.wait_for(loop.run_in_executor(_dns_pool, socket.gethostbyaddr, ip), timeout)
            host = name[0]
            if host and host != ip and not re.fullmatch(r"[\d.]+", host):
                return ip, host
        except (OSError, asyncio.TimeoutError):
            pass
        return ip, None

    res = await asyncio.gather(*(one(ip) for ip in ips))
    return {ip: h for ip, h in res if h}


# --------------------------------------------------------------------------- SSDP / UPnP
SSDP_ADDR = ("239.255.255.250", 1900)


def _msearch(st: str) -> bytes:
    return (f"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
            f"MX: 2\r\nST: {st}\r\nUSER-AGENT: NETSniffer/1.0 UPnP/1.1\r\n\r\n").encode()


def _headers(data: bytes) -> dict[str, str]:
    out = {}
    for line in data.decode("utf-8", "replace").split("\r\n")[1:]:
        k, sep, v = line.partition(":")
        if sep:
            out[k.strip().lower()] = v.strip()
    return out


def _xml_text(node, tag: str) -> str | None:
    for el in node.iter():
        if el.tag.split("}")[-1] == tag and el.text and el.text.strip():
            return el.text.strip()
    return None


async def ssdp_discover(wait: float = 3.0) -> dict[str, dict]:
    packets = [(_msearch(st), SSDP_ADDR) for st in ("ssdp:all", "upnp:rootdevice")]
    found: dict[str, dict] = {}
    for data, ip in await _udp_exchange(packets, wait, multicast_ttl=2, repeat=2):
        if not is_local_ip(ip):
            continue
        h = _headers(data)
        entry = found.setdefault(ip, {"st": set(), "location": None, "server": None})
        if h.get("st"):
            entry["st"].add(h["st"])
        if h.get("location") and not entry["location"]:
            entry["location"] = h["location"]
        if h.get("server"):
            entry["server"] = h["server"]

    async with httpx.AsyncClient(timeout=2.5, follow_redirects=False) as client:
        async def describe(ip: str, entry: dict) -> None:
            loc = entry.get("location")
            m = re.match(r"https?://([^:/]+)", loc or "")
            if not loc or not m or not is_local_ip(m.group(1)):
                return
            try:
                r = await client.get(loc)
                if r.status_code != 200 or len(r.content) > 512_000:
                    return
                root = ET.fromstring(r.content)
                entry.update({
                    "friendly_name": _xml_text(root, "friendlyName"),
                    "manufacturer": _xml_text(root, "manufacturer"),
                    "model": _xml_text(root, "modelName"),
                    "model_number": _xml_text(root, "modelNumber"),
                    "model_description": _xml_text(root, "modelDescription"),
                    "device_type": _xml_text(root, "deviceType"),
                    "presentation_url": _xml_text(root, "presentationURL"),
                })
                types = [el.text for el in root.iter() if el.tag.split("}")[-1] == "deviceType" and el.text]
                entry["device_types"] = types
            except (httpx.HTTPError, ET.ParseError, ValueError):
                return
            except Exception:  # noqa: BLE001 - defusedxml raises custom errors on hostile XML
                return

        await asyncio.gather(*(describe(ip, e) for ip, e in found.items()))
    for e in found.values():
        e["st"] = sorted(e["st"])
        sts = " ".join(e["st"] + e.get("device_types", []))
        e["igd"] = "InternetGatewayDevice" in sts or "WANIPConnection" in sts or "WANPPPConnection" in sts
    return found


# --------------------------------------------------------------------------- WS-Discovery
def _wsd_probe() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
        'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">'
        f'<e:Header><w:MessageID>uuid:{uuid.uuid4()}</w:MessageID>'
        '<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
        '<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>'
        '</e:Header><e:Body><d:Probe/></e:Body></e:Envelope>'
    ).encode()


async def wsd_discover(wait: float = 2.5) -> dict[str, dict]:
    out: dict[str, dict] = {}
    res = await _udp_exchange([(_wsd_probe(), ("239.255.255.250", 3702))], wait, multicast_ttl=2, repeat=2)
    for data, ip in res:
        if not is_local_ip(ip):
            continue
        text = data.decode("utf-8", "replace")
        types = " ".join(re.findall(r"<[^>]*:?Types[^>]*>([^<]+)<", text))
        xaddrs = " ".join(re.findall(r"<[^>]*:?XAddrs[^>]*>([^<]+)<", text))
        e = out.setdefault(ip, {"types": "", "xaddrs": ""})
        e["types"] = (e["types"] + " " + types).strip()
        e["xaddrs"] = e["xaddrs"] or xaddrs
        e["camera"] = "NetworkVideoTransmitter" in e["types"]
        e["printer"] = bool(re.search(r"Print|wprt", e["types"]))
        e["computer"] = "Computer" in e["types"]
    return out


# --------------------------------------------------------------------------- mDNS / DNS-SD browser
MDNS_TYPES = [
    "_http._tcp.local.", "_workstation._tcp.local.", "_device-info._tcp.local.", "_airplay._tcp.local.",
    "_raop._tcp.local.", "_googlecast._tcp.local.", "_spotify-connect._tcp.local.", "_ipp._tcp.local.",
    "_ipps._tcp.local.", "_printer._tcp.local.", "_pdl-datastream._tcp.local.", "_scanner._tcp.local.",
    "_uscan._tcp.local.", "_hap._tcp.local.", "_companion-link._tcp.local.", "_smb._tcp.local.",
    "_afpovertcp._tcp.local.", "_ssh._tcp.local.", "_sftp-ssh._tcp.local.", "_rfb._tcp.local.",
    "_sonos._tcp.local.", "_hue._tcp.local.", "_matter._tcp.local.", "_matterc._udp.local.",
    "_amzn-wplay._tcp.local.", "_androidtvremote2._tcp.local.", "_nvstream._tcp.local.", "_rtsp._tcp.local.",
    "_daap._tcp.local.", "_apple-mobdev2._tcp.local.", "_esphomelib._tcp.local.", "_home-assistant._tcp.local.",
    "_octoprint._tcp.local.", "_mqtt._tcp.local.", "_plexmediasvr._tcp.local.", "_touch-able._tcp.local.",
    "_adisk._tcp.local.", "_meshcop._udp.local.", "_trel._udp.local.", "_sleep-proxy._udp.local.",
    "_miio._udp.local.", "_shelly._tcp.local.", "_elg._tcp.local.", "_nanoleafapi._tcp.local.",
]
MODEL_KEYS = ("model", "md", "am", "rpmd", "ty", "product", "usb_mdl", "mdl", "modelname")


class MdnsBrowser:
    """Passive, long-running DNS-SD listener. Keeps a per-IP cache of names, services and models."""

    def __init__(self) -> None:
        self.cache: dict[str, dict] = {}
        self._azc = None
        self._browser = None
        self._tasks: set[asyncio.Task] = set()
        self.on_update = None

    async def start(self) -> None:
        try:
            from zeroconf import IPVersion
            from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf
        except ImportError:
            return
        try:
            self._azc = AsyncZeroconf(ip_version=IPVersion.V4Only)
            self._browser = AsyncServiceBrowser(self._azc.zeroconf, MDNS_TYPES, handlers=[self._on_change])
        except Exception as exc:  # noqa: BLE001
            log.warning("mDNS unavailable: %s", exc)

    async def stop(self) -> None:
        try:
            if self._browser:
                await self._browser.async_cancel()
            if self._azc:
                await self._azc.async_close()
        except Exception:  # noqa: BLE001
            pass

    def _on_change(self, zeroconf, service_type: str, name: str, state_change) -> None:
        if state_change.name == "Removed":
            return
        t = asyncio.ensure_future(self._resolve(service_type, name))
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _resolve(self, service_type: str, name: str) -> None:
        from zeroconf import IPVersion
        from zeroconf.asyncio import AsyncServiceInfo
        info = AsyncServiceInfo(service_type, name)
        try:
            if not await info.async_request(self._azc.zeroconf, 3000):
                return
        except Exception:  # noqa: BLE001
            return
        props: dict[str, str] = {}
        for k, v in (info.properties or {}).items():
            try:
                props[k.decode("utf-8", "replace").lower()] = (v or b"").decode("utf-8", "replace")
            except AttributeError:
                continue
        instance = name[: -len(service_type) - 1] if name.endswith(service_type) else name
        host = re.sub(r"\.local\.?$", "", info.server or "") or None
        for ip in info.parsed_addresses(IPVersion.V4Only):
            if not is_local_ip(ip):
                continue
            e = self.cache.setdefault(ip, {"services": [], "names": [], "txt": {}, "host": None, "ts": 0})
            stype = service_type.replace(".local.", "")
            if stype not in e["services"]:
                e["services"].append(stype)
            if instance and instance not in e["names"]:
                e["names"].append(instance)
            if host:
                e["host"] = host
            for k in MODEL_KEYS + ("fn", "manufacturer", "usb_mfg", "note"):
                if props.get(k) and k not in e["txt"]:
                    e["txt"][k] = props[k][:80]
            e["ts"] = time.time()
            if self.on_update:
                try:
                    self.on_update(ip)
                except Exception:  # noqa: BLE001
                    pass

    def get(self, ip: str) -> dict | None:
        return self.cache.get(ip)


def mdns_model(entry: dict | None) -> str | None:
    if not entry:
        return None
    txt = entry.get("txt", {})
    for k in MODEL_KEYS:
        v = txt.get(k)
        if v and len(v) > 1 and not re.fullmatch(r"[0-9a-f]{12,}|[\d,.\s]+|MacSamba|Xserve", v, re.I):
            return v
    return None


def mdns_friendly(entry: dict | None) -> str | None:
    if not entry:
        return None
    if entry.get("txt", {}).get("fn"):
        return entry["txt"]["fn"]
    names = [n for n in entry.get("names", []) if not re.fullmatch(r"[0-9A-Fa-f@:-]{12,}.*", n)]
    for n in names:
        n2 = re.sub(r"^[0-9A-F]{12}@", "", n)
        if 2 < len(n2) < 64:
            return n2
    return entry.get("host")
