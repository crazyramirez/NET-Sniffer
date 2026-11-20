"""Local network context: primary interface, subnet, gateway, DNS, Wi-Fi link and public IP."""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import struct
import time
from pathlib import Path

import httpx
import psutil

from ..config import IS_MAC, IS_WINDOWS
from .utils import IP_RE, is_local_ip, norm_mac, run_cmd

CF_HEADERS = {"Referer": "https://speed.cloudflare.com/", "User-Agent": "NETSniffer"}
_public_cache: dict = {"ts": 0, "data": None}


def primary_ip() -> str | None:
    for target in ("1.1.1.1", "8.8.8.8", "192.168.0.1"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            continue
        finally:
            s.close()
    for addrs in psutil.net_if_addrs().values():
        for a in addrs:
            if a.family == socket.AF_INET and is_local_ip(a.address) and not a.address.startswith("127."):
                return a.address
    return None


def interface_for_ip(ip: str) -> tuple[str | None, str | None, str | None]:
    """Return (interface name, netmask, mac) for the interface carrying `ip`."""
    for name, addrs in psutil.net_if_addrs().items():
        if any(a.family == socket.AF_INET and a.address == ip for a in addrs):
            mask = next((a.netmask for a in addrs if a.family == socket.AF_INET and a.address == ip), None)
            mac = next((norm_mac(a.address) for a in addrs if a.family == psutil.AF_LINK), None)
            return name, mask, mac
    return None, None, None


def default_gateway(local_ip: str | None) -> str | None:
    if IS_WINDOWS:
        out = run_cmd(["route", "print", "-4", "0.0.0.0"])
        best: tuple[int, str] | None = None
        for m in re.finditer(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\S+)\s+(\S+)\s+(\d+)", out, re.M):
            gw, iface, metric = m.group(1), m.group(2), int(m.group(3))
            if not IP_RE.fullmatch(gw):
                continue
            if iface == local_ip:
                return gw
            if best is None or metric < best[0]:
                best = (metric, gw)
        return best[1] if best else None
    if IS_MAC:
        m = re.search(r"gateway:\s*(\S+)", run_cmd(["route", "-n", "get", "default"]))
        return m.group(1) if m and IP_RE.fullmatch(m.group(1)) else None
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            f = line.split()
            if len(f) > 2 and f[1] == "00000000" and int(f[3], 16) & 2:
                return socket.inet_ntoa(struct.pack("<L", int(f[2], 16)))
    except OSError:
        pass
    m = re.search(r"default via (\S+)", run_cmd(["ip", "route", "show", "default"]))
    return m.group(1) if m else None


def dns_servers(local_ip: str | None) -> list[str]:
    servers: list[str] = []
    if IS_WINDOWS:
        try:
            import winreg
            base = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
                for i in range(winreg.QueryInfoKey(root)[0]):
                    with winreg.OpenKey(root, winreg.EnumKey(root, i)) as k:
                        vals = {}
                        for name in ("IPAddress", "DhcpIPAddress", "NameServer", "DhcpNameServer"):
                            try:
                                vals[name] = winreg.QueryValueEx(k, name)[0]
                            except OSError:
                                pass
                        ips = vals.get("IPAddress") or []
                        ips = ips if isinstance(ips, list) else [ips]
                        if local_ip and local_ip not in ips and vals.get("DhcpIPAddress") != local_ip:
                            continue
                        raw = vals.get("NameServer") or vals.get("DhcpNameServer") or ""
                        servers += [s for s in re.split(r"[ ,]+", raw) if IP_RE.fullmatch(s)]
        except OSError:
            pass
    elif IS_MAC:
        servers = re.findall(r"nameserver\[\d+\]\s*:\s*(\S+)", run_cmd(["scutil", "--dns"]))
    else:
        try:
            servers = re.findall(r"^nameserver\s+(\S+)", Path("/etc/resolv.conf").read_text(), re.M)
        except OSError:
            pass
        if not servers or servers == ["127.0.0.53"]:
            found = IP_RE.findall(run_cmd(["resolvectl", "dns"]))
            servers = found or servers
    seen: list[str] = []
    for s in servers:
        if IP_RE.fullmatch(s) and s not in seen:
            seen.append(s)
    return seen[:6]


def _norm_auth(value: str) -> str:
    v = value.upper()
    for key in ("WPA3", "WPA2", "WPA", "WEP"):
        if key in v:
            return f"{key}-Enterprise" if "ENTERPRISE" in v or "802.1X" in v or "EAP" in v else key
    if any(x in v for x in ("OPEN", "ABIERT", "OUVERT", "OFFEN", "APERT", "NONE", "开放", "オープン")):
        return "OPEN"
    return value.strip()


def wifi_info() -> dict | None:
    try:
        if IS_WINDOWS:
            return _wifi_windows()
        if IS_MAC:
            return _wifi_mac()
        return _wifi_linux()
    except Exception:  # noqa: BLE001 - best effort
        return None


def _wifi_windows() -> dict | None:
    out = run_cmd(["netsh", "wlan", "show", "interfaces"])
    if "SSID" not in out:
        return None
    info: dict = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key_s, val = key.strip(), val.strip()
        k = key_s.lower()
        if k == "ssid":
            info["ssid"] = val
        elif "bssid" in k:
            info["bssid"] = norm_mac(val) or val
        elif k == "rssi":
            info["rssi"] = int(re.sub(r"[^\d-]", "", val) or 0)
        elif re.fullmatch(r"\d{1,3}\s?%", val):
            info["signal"] = int(val.rstrip("% "))
        elif re.fullmatch(r"\d(\.\d)?\s?GHz", val):
            info["band"] = val
        elif val.startswith("802.11"):
            info["radio"] = val
        elif "mbps" in k:
            n = re.sub(r"[^\d.]", "", val)
            info.setdefault("rates", []).append(float(n) if n else 0)
        elif any(w in k for w in ("canal", "channel", "kanal", "canale", "通道", "频道", "チャネル")) and val.isdigit():
            info["channel"] = int(val)
        elif re.search(r"WPA|WEP|Open|Abierta|Ouvert|Offen|Aperta|开放|オープン", val, re.I) and "auth" not in info \
                and not re.search(r"cifrado|cipher|chiffr|verschl|crittograf|加密|暗号", k):
            info["auth"] = _norm_auth(val)
        elif re.fullmatch(r"CCMP|GCMP(-256)?|TKIP|WEP|None|Ninguno|Aucun|Keine|Nessuno|无|なし", val, re.I):
            info["cipher"] = val.upper()
    if "ssid" not in info:
        return None
    rates = info.pop("rates", [])
    if rates:
        info["rx_rate"] = rates[0]
        info["tx_rate"] = rates[1] if len(rates) > 1 else rates[0]
    return info


def _wifi_mac() -> dict | None:
    out = run_cmd(["system_profiler", "SPAirPortDataType", "-json"], timeout=15)
    data = json.loads(out or "{}")
    for item in data.get("SPAirPortDataType", []):
        for iface in item.get("spairport_airport_interfaces", []):
            cur = iface.get("spairport_current_network_information")
            if not cur:
                continue
            chan = str(cur.get("spairport_network_channel", ""))
            sec = str(cur.get("spairport_security_mode", "")).replace("spairport_security_mode_", "")
            sig = str(cur.get("spairport_signal_noise", ""))
            rssi = re.search(r"(-\d+)\s*dBm", sig)
            band = re.search(r"(\d(?:\.\d)?)\s*GHz", chan)
            return {
                "ssid": cur.get("_name", ""),
                "channel": int(re.match(r"\d+", chan).group()) if re.match(r"\d+", chan) else None,
                "band": f"{band.group(1)} GHz" if band else None,
                "auth": _norm_auth(sec.replace("_", " ")),
                "rssi": int(rssi.group(1)) if rssi else None,
                "signal": max(0, min(100, 2 * (int(rssi.group(1)) + 100))) if rssi else None,
                "radio": cur.get("spairport_network_phymode"),
                "tx_rate": cur.get("spairport_network_rate"),
            }
    return None


def _wifi_linux() -> dict | None:
    out = run_cmd(["nmcli", "-t", "-f", "ACTIVE,SSID,BSSID,CHAN,FREQ,SIGNAL,SECURITY,RATE", "dev", "wifi"])
    for line in out.splitlines():
        parts = re.split(r"(?<!\\):", line)
        if len(parts) >= 8 and parts[0] in ("yes", "sí", "oui", "ja", "sì", "是", "はい"):
            freq = re.sub(r"[^\d]", "", parts[4])
            return {
                "ssid": parts[1].replace("\\:", ":"),
                "bssid": norm_mac(parts[2].replace("\\:", ":")),
                "channel": int(parts[3]) if parts[3].isdigit() else None,
                "band": ("5 GHz" if freq.startswith("5") else "6 GHz" if freq.startswith("6") else "2.4 GHz")
                if freq else None,
                "signal": int(parts[5]) if parts[5].isdigit() else None,
                "auth": _norm_auth(parts[6] or "OPEN"),
                "tx_rate": parts[7],
            }
    ssid = run_cmd(["iwgetid", "-r"]).strip()
    return {"ssid": ssid} if ssid else None


async def public_info(force: bool = False) -> dict | None:
    if not force and _public_cache["data"] and time.time() - _public_cache["ts"] < 600:
        return _public_cache["data"]
    try:
        async with httpx.AsyncClient(timeout=6, headers=CF_HEADERS) as c:
            r = await c.get("https://speed.cloudflare.com/meta")
            r.raise_for_status()
            m = r.json()
        data = {
            "ip": m.get("clientIp"), "isp": m.get("asOrganization"), "asn": m.get("asn"),
            "city": m.get("city"), "region": m.get("region"), "country": m.get("country"),
            "colo": (m.get("colo") or {}).get("city") or (m.get("colo") or {}).get("iata"),
        }
        _public_cache.update(ts=time.time(), data=data)
        return data
    except (httpx.HTTPError, ValueError):
        return _public_cache["data"]


def network_info() -> dict:
    ip = primary_ip()
    iface, mask, mac = interface_for_ip(ip) if ip else (None, None, None)
    net = None
    if ip and mask:
        try:
            net = ipaddress.ip_network(f"{ip}/{mask}", strict=False)
        except ValueError:
            net = None
    if ip and net is None:
        net = ipaddress.ip_network(f"{ip}/24", strict=False)
    gw = default_gateway(ip)
    return {
        "hostname": socket.gethostname(),
        "interface": iface,
        "ip": ip,
        "mac": mac,
        "netmask": mask,
        "cidr": str(net) if net else None,
        "prefix": net.prefixlen if net else None,
        "hosts": max(0, net.num_addresses - 2) if net else 0,
        "gateway": gw,
        "dns": dns_servers(ip),
        "wifi": wifi_info(),
        "connection": "wifi" if iface and re.search(r"wi-?fi|wlan|wl|en0|airport", iface, re.I) else "ethernet",
    }


def scan_targets(info: dict, max_hosts: int = 4094) -> list[str]:
    """Hosts to probe. Large subnets are reduced to the /22 around the local IP."""
    if not info.get("cidr") or not info.get("ip"):
        return []
    net = ipaddress.ip_network(info["cidr"])
    if net.num_addresses - 2 > max_hosts:
        net = ipaddress.ip_network(f"{info['ip']}/22", strict=False)
    return [str(h) for h in net.hosts() if is_local_ip(str(h))]
