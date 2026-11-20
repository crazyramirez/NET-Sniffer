"""Device access control through the administration interfaces of equipment you own.

Blocking is applied where it belongs — on your router/gateway — using its official management
channels and *your* administrator credentials:

- ``ssh``    OpenWrt / any Linux-based router: an nftables set (or iptables chain) of blocked MACs
- ``fritz``  AVM FRITZ!Box: TR-064 ``X_AVM-DE_HostFilter`` (official AVM API)
- ``local``  This machine is the gateway (e.g. Raspberry Pi hotspot/router): local nftables/iptables

The app never impersonates other hosts (no ARP spoofing / deauth); without a configured backend
the UI explains how to block from the router itself.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
import time

from .. import licensing
from ..config import IS_LINUX

log = logging.getLogger("netsniffer.blocking")
MAC_STRICT = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
IP_STRICT = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


class BlockError(RuntimeError):
    pass


def _script(macs: list[str], firewall: str) -> str:
    macs = [m for m in macs if MAC_STRICT.match(m)]  # strict validation: nothing else reaches the shell
    if firewall == "iptables":
        lines = ["iptables -N NETSNIFFER 2>/dev/null || true",
                 "iptables -C FORWARD -j NETSNIFFER 2>/dev/null || iptables -I FORWARD 1 -j NETSNIFFER",
                 "iptables -F NETSNIFFER"]
        lines += [f"iptables -A NETSNIFFER -m mac --mac-source {m} -j DROP" for m in macs]
    else:
        lines = ["nft add table inet netsniffer",
                 "nft add set inet netsniffer blocked '{ type ether_addr; }'",
                 "nft add chain inet netsniffer fwd '{ type filter hook forward priority -5; policy accept; }'",
                 "nft list chain inet netsniffer fwd | grep -q '@blocked' || "
                 "nft add rule inet netsniffer fwd ether saddr @blocked drop",
                 "nft flush set inet netsniffer blocked"]
        if macs:
            lines.append(f"nft add element inet netsniffer blocked '{{ {', '.join(macs)} }}'")
    lines.append("echo NETSNIFFER_OK")
    return " && ".join(lines)


class SSHBackend:
    name = "ssh"

    def __init__(self, s: dict, save) -> None:
        self.s, self.save = s, save

    async def _connect(self):
        import asyncssh
        host, port = self.s.get("block_host"), int(self.s.get("block_port") or 22)
        if not host:
            raise BlockError("block_not_configured")
        pinned = self.s.get("block_hostkey")
        kwargs = dict(username=self.s.get("block_user") or "root", password=self.s.get("block_password") or None,
                      connect_timeout=8)
        if pinned:
            kwargs["known_hosts"] = asyncssh.import_known_hosts(f"{host} {pinned}\n[{host}]:{port} {pinned}\n")
        else:
            kwargs["known_hosts"] = None  # trust on first use; key is pinned right after
        try:
            conn = await asyncssh.connect(host, port, **kwargs)
        except asyncssh.HostKeyNotVerifiable as exc:
            raise BlockError("block_hostkey_changed") from exc
        except (OSError, asyncssh.Error) as exc:
            raise BlockError(f"block_connect_failed:{exc}") from exc
        if not pinned:
            key = conn.get_server_host_key()
            if key:
                self.save({"block_hostkey": key.export_public_key().decode().strip()})
        return conn

    async def apply(self, blocked: list[dict]) -> None:
        conn = await self._connect()
        async with conn:
            res = await conn.run(_script([d["mac"] for d in blocked if d.get("mac")],
                                         self.s.get("block_firewall") or "nft"), check=False, timeout=20)
            if "NETSNIFFER_OK" not in (res.stdout or ""):
                raise BlockError(f"block_command_failed:{(res.stderr or res.stdout or '').strip()[:200]}")

    async def test(self) -> str:
        conn = await self._connect()
        async with conn:
            res = await conn.run("uname -a; (command -v nft || command -v iptables)", check=False, timeout=10)
            return (res.stdout or "").strip()[:300]


class LocalBackend(SSHBackend):
    name = "local"

    async def apply(self, blocked: list[dict]) -> None:
        if not IS_LINUX:
            raise BlockError("block_local_linux_only")
        script = _script([d["mac"] for d in blocked if d.get("mac")], self.s.get("block_firewall") or "nft")
        proc = await asyncio.create_subprocess_exec("sh", "-c", script, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), 20)
        if b"NETSNIFFER_OK" not in out:
            raise BlockError(f"block_command_failed:{err.decode(errors='replace')[:200]}")

    async def test(self) -> str:
        if not IS_LINUX:
            raise BlockError("block_local_linux_only")
        proc = await asyncio.create_subprocess_exec("sh", "-c", "id -u; command -v nft || command -v iptables",
                                                    stdout=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate()
        text = out.decode().strip()
        if not text.startswith("0"):
            raise BlockError("block_local_needs_root")
        return text


class FritzBackend:
    name = "fritz"

    def __init__(self, s: dict, save) -> None:
        self.s = s

    def _fc(self):
        from fritzconnection import FritzConnection
        if not self.s.get("block_host"):
            raise BlockError("block_not_configured")
        return FritzConnection(address=self.s["block_host"], user=self.s.get("block_user") or None,
                               password=self.s.get("block_password") or None, timeout=8)

    async def apply(self, blocked: list[dict], unblocked: list[dict] | None = None) -> None:
        def work() -> None:
            fc = self._fc()
            for d in blocked:
                if IP_STRICT.match(d.get("ip") or ""):
                    fc.call_action("X_AVM-DE_HostFilter1", "DisallowWANAccessByIP", NewIPv4Address=d["ip"],
                                   NewDisallow=1)
            for d in unblocked or []:
                if IP_STRICT.match(d.get("ip") or ""):
                    fc.call_action("X_AVM-DE_HostFilter1", "DisallowWANAccessByIP", NewIPv4Address=d["ip"],
                                   NewDisallow=0)
        try:
            await asyncio.to_thread(work)
        except BlockError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BlockError(f"block_connect_failed:{exc}") from exc

    async def test(self) -> str:
        def work() -> str:
            fc = self._fc()
            return f"{fc.modelname} · FRITZ!OS {fc.system_version}"
        try:
            return await asyncio.to_thread(work)
        except Exception as exc:  # noqa: BLE001
            raise BlockError(f"block_connect_failed:{exc}") from exc


BACKENDS = {"ssh": SSHBackend, "local": LocalBackend, "fritz": FritzBackend}


def rule_active(rule: dict, now: dt.datetime | None = None) -> bool:
    """A rule blocks while paused_until is in the future or the current time falls in a schedule slot.
    Schedule slot: {"days": [0..6] (Mon=0), "start": "HH:MM", "end": "HH:MM"} (end < start spans midnight)."""
    if not rule.get("enabled", True):
        return False
    now = now or dt.datetime.now()
    if float(rule.get("paused_until") or 0) > now.timestamp():
        return True
    minutes = now.hour * 60 + now.minute
    for slot in rule.get("schedule") or []:
        try:
            sh, sm = map(int, slot["start"].split(":"))
            eh, em = map(int, slot["end"].split(":"))
        except (KeyError, ValueError):
            continue
        start, end = sh * 60 + sm, eh * 60 + em
        days = slot.get("days") or list(range(7))
        today, yesterday = now.weekday(), (now.weekday() - 1) % 7
        if start <= end:
            if today in days and start <= minutes < end:
                return True
        else:  # overnight, e.g. 22:00 → 07:00
            if (today in days and minutes >= start) or (yesterday in days and minutes < end):
                return True
    return False


class BlockManager:
    def __init__(self, db, hub, notifier) -> None:
        self.db, self.hub, self.notifier = db, hub, notifier
        self.applied: dict[str, dict] = {}
        self.last_error: str | None = None
        self.last_apply: float | None = None
        self._lock = asyncio.Lock()

    def backend(self):
        s = self.db.settings()
        cls = BACKENDS.get(s.get("block_backend") or "none")
        return cls(s, self.db.set_settings) if cls else None

    def desired(self) -> dict[str, dict]:
        devices = {d["id"]: d for d in self.db.devices()}
        want = {i: {"mac": d["mac"], "ip": d["ip"], "reason": "manual"} for i, d in devices.items() if d["blocked"]}
        for rule in self.db.rules():
            if rule_active(rule):
                for did in rule.get("devices") or []:
                    if did in devices and did not in want:
                        want[did] = {"mac": devices[did]["mac"], "ip": devices[did]["ip"], "reason": "parental",
                                     "rule": rule.get("name")}
        return want

    def status(self) -> dict:
        s = self.db.settings()
        return {"backend": s.get("block_backend") or "none", "applied": list(self.applied),
                "last_error": self.last_error, "last_apply": self.last_apply,
                "allowed": licensing.has(s, "blocking")}

    async def reconcile(self, force: bool = False) -> None:
        async with self._lock:
            s = self.db.settings()
            backend = self.backend()
            if not backend or not licensing.has(s, "blocking"):
                self.applied = {}
                return
            want = self.desired()
            if not force and set(want) == set(self.applied) and \
                    all(want[k]["ip"] == self.applied[k]["ip"] for k in want):
                return
            removed = [v for k, v in self.applied.items() if k not in want]
            try:
                if isinstance(backend, FritzBackend):
                    await backend.apply(list(want.values()), removed)
                else:
                    await backend.apply(list(want.values()))
                self.applied = want
                self.last_error = None
                self.last_apply = time.time()
            except BlockError as exc:
                self.last_error = str(exc)
                log.warning("blocking apply failed: %s", exc)
            await self.hub.broadcast("blocking", self.status())

    async def loop(self) -> None:
        await asyncio.sleep(5)
        last_force = 0.0
        while True:
            try:
                force = time.time() - last_force > 600  # re-assert periodically (router reboots lose rules)
                await self.reconcile(force=force)
                if force:
                    last_force = time.time()
            except Exception:  # noqa: BLE001
                log.exception("reconcile")
            await asyncio.sleep(30)
