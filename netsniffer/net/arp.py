"""Neighbor (ARP) table access and unprivileged host wake-up.

Discovery relies on the operating system's own ARP resolution: sending one harmless UDP datagram
to each address of the local subnet makes the OS resolve it, so every host that is present answers
the ARP request and appears in the neighbor table. No raw sockets, spoofing or admin rights needed.
"""
from __future__ import annotations

import asyncio
import json
import re
import socket

from ..config import IS_MAC, IS_WINDOWS
from .utils import IP_RE, MAC_RE, arun_cmd, norm_mac

FRESH_STATES = {"reachable", "delay", "probe", "permanent", "noarp"}


async def neighbor_table() -> dict[str, dict]:
    """ip -> {"mac", "state"} (state may be None when the OS does not expose it)."""
    table: dict[str, dict] = {}
    if IS_WINDOWS:
        ps = ("Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
              "Select-Object IPAddress,LinkLayerAddress,@{n='State';e={$_.State.ToString()}} | ConvertTo-Json -Compress")
        out = await arun_cmd(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=15)
        try:
            rows = json.loads(out) if out.strip() else []
            rows = rows if isinstance(rows, list) else [rows]
            for r in rows:
                mac = norm_mac(r.get("LinkLayerAddress") or "")
                ip = r.get("IPAddress")
                if mac and ip and IP_RE.fullmatch(ip):
                    table[ip] = {"mac": mac, "state": str(r.get("State", "")).lower()}
        except ValueError:
            pass
        if not table:
            out = await arun_cmd(["arp", "-a"])
            for line in out.splitlines():
                ip_m, mac_m = IP_RE.search(line), MAC_RE.search(line)
                if ip_m and mac_m and (mac := norm_mac(mac_m.group())):
                    table[ip_m.group()] = {"mac": mac, "state": None}
        return table
    if IS_MAC:
        out = await arun_cmd(["arp", "-an"])
        for line in out.splitlines():
            m = re.search(r"\((\d+\.\d+\.\d+\.\d+)\) at ([0-9a-fA-F:]+)", line)
            if m and (mac := norm_mac(m.group(2))):
                table[m.group(1)] = {"mac": mac, "state": "permanent" if "permanent" in line else None}
        return table
    out = await arun_cmd(["ip", "-4", "neigh", "show"])
    for line in out.splitlines():
        m = re.match(r"(\d+\.\d+\.\d+\.\d+) .*lladdr ([0-9a-fA-F:]+)\s+(?:router\s+)?(\w+)?", line)
        if m and (mac := norm_mac(m.group(2))):
            table[m.group(1)] = {"mac": mac, "state": (m.group(3) or "").lower() or None}
    if not table:
        try:
            with open("/proc/net/arp") as fh:
                for line in fh.readlines()[1:]:
                    f = line.split()
                    if len(f) >= 4 and f[2] != "0x0" and (mac := norm_mac(f[3])):
                        table[f[0]] = {"mac": mac, "state": None}
        except OSError:
            pass
    return table


async def poke(targets: list[str], batch: int = 96, pause: float = 0.04) -> None:
    """Send one tiny UDP datagram (discard port 9) to each target so the OS performs ARP resolution."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        for i in range(0, len(targets), batch):
            for ip in targets[i:i + batch]:
                try:
                    sock.sendto(b"\x00", (ip, 9))
                except OSError:
                    pass
            await asyncio.sleep(pause)
    finally:
        sock.close()


def is_fresh(entry: dict) -> bool:
    state = entry.get("state")
    return state is None or state in FRESH_STATES
