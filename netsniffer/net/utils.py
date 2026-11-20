"""Shared helpers for network modules."""
from __future__ import annotations

import asyncio
import ipaddress
import re
import subprocess
import sys

from ..config import IS_WINDOWS

MAC_RE = re.compile(r"([0-9a-fA-F]{1,2}[:-]){5}[0-9a-fA-F]{1,2}")
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


class NotLocalError(ValueError):
    """Raised when a target is outside the local/private address space."""


def norm_mac(mac: str | None) -> str | None:
    if not mac:
        return None
    parts = re.split(r"[:-]", mac.strip())
    if len(parts) != 6:
        return None
    try:
        mac = ":".join(f"{int(p, 16):02x}" for p in parts)
    except ValueError:
        return None
    if mac in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
        return None
    if int(mac[:2], 16) & 0x01:  # multicast
        return None
    return mac


def is_randomized_mac(mac: str | None) -> bool:
    """Locally administered bit set → private/random MAC (iOS, Android, Windows privacy)."""
    return bool(mac) and bool(int(mac[:2], 16) & 0x02)


def is_local_ip(ip: str) -> bool:
    """Only RFC1918 / link-local / loopback / CGNAT-free private ranges are allowed as scan targets."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version != 4 or addr in _CGNAT:
        return False
    return addr.is_private and not (addr.is_multicast or addr.is_unspecified or addr.is_reserved)


_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def require_local(ip: str) -> str:
    if not is_local_ip(ip):
        raise NotLocalError(ip)
    return ip


def _decode(data: bytes) -> str:
    if IS_WINDOWS:
        for enc in ("utf-8", "oem", "mbcs"):
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
    return data.decode("utf-8", errors="replace")


def run_cmd(args: list[str], timeout: float = 10.0) -> str:
    """Run a system command without flashing a console window; return stdout ('' on failure)."""
    kwargs: dict = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si
    try:
        res = subprocess.run(args, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, **kwargs)
        return _decode(res.stdout)
    except (OSError, subprocess.SubprocessError):
        return ""


async def arun_cmd(args: list[str], timeout: float = 10.0) -> str:
    return await asyncio.to_thread(run_cmd, args, timeout)


def run_cmd_rc(args: list[str], timeout: float = 15.0) -> tuple[int, str]:
    kwargs: dict = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x08000000
    try:
        res = subprocess.run(args, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, **kwargs)
        return res.returncode, _decode(res.stdout + res.stderr)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


async def tcp_probe(ip: str, port: int, timeout: float = 0.8) -> tuple[bool, float | None]:
    """Returns (host_responded, rtt_ms). A refused connection still proves the host is alive."""
    loop = asyncio.get_running_loop()
    start = loop.time()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
        rtt = (loop.time() - start) * 1000
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), 0.5)
        except (asyncio.TimeoutError, OSError):
            pass
        return True, rtt
    except ConnectionRefusedError:
        return True, (loop.time() - start) * 1000
    except (asyncio.TimeoutError, OSError):
        return False, None


def platform_name() -> str:
    if IS_WINDOWS:
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"
