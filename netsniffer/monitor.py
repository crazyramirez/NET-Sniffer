"""Internet / gateway availability monitor, outage detection and live host bandwidth."""
from __future__ import annotations

import asyncio
import socket
import time

import psutil

from .db import Database
from .hub import Hub
from .net.utils import tcp_probe
from .notify import Notifier

INTERNET_TARGETS = [("1.1.1.1", 443), ("8.8.8.8", 443), ("9.9.9.9", 443)]


class Monitor:
    def __init__(self, db: Database, hub: Hub, notifier: Notifier, engine) -> None:
        self.db, self.hub, self.notifier, self.engine = db, hub, notifier, engine
        self.state: dict = {"status": "unknown", "latency": None, "gw_ok": None, "dns_ok": None,
                            "since": time.time(), "last": None}
        self._fails = 0
        self._first_fail: float | None = None
        self._outage_id: int | None = None
        self._outage_scope: str | None = None
        self.bandwidth: dict = {"rx": 0.0, "tx": 0.0, "ts": time.time()}
        self._recent: list[tuple[float, bool]] = []

    async def _dns_ok(self) -> bool:
        try:
            await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo("www.cloudflare.com", 443,
                                                                          type=socket.SOCK_STREAM), 3)
            return True
        except (OSError, asyncio.TimeoutError):
            return False

    async def check(self) -> dict:
        gw = (self.engine.net or {}).get("gateway")
        gw_task = asyncio.gather(*(tcp_probe(gw, p, 1.2) for p in (53, 80, 443))) if gw else None
        inet = await asyncio.gather(*(tcp_probe(ip, port, 2.5) for ip, port in INTERNET_TARGETS))
        gw_res = await gw_task if gw_task else []
        ok = any(r[0] for r in inet)
        lat = min((r[1] for r in inet if r[0] and r[1] is not None), default=None)
        gw_ok = any(r[0] for r in gw_res) if gw_res else None
        dns_ok = await self._dns_ok() if ok else False
        now = time.time()
        self.db.add_sample(now, lat, ok, bool(gw_ok), dns_ok)
        self._recent = [(t, o) for t, o in self._recent if now - t < 600] + [(now, ok)]
        loss = round(100 * sum(1 for _, o in self._recent if not o) / len(self._recent), 1)
        prev = self.state["status"]
        if ok:
            status = "degraded" if (lat and lat > 250) or not dns_ok else "online"
            self._fails = 0
            self._first_fail = None
            if self._outage_id is not None:
                self.db.close_outage(self._outage_id, now)
                start = self.db.q("SELECT start FROM outages WHERE id=?", (self._outage_id,))[0]["start"]
                self._outage_id = None
                await self.notifier.alert("internet_up", "info", None,
                                          {"duration": _fmt_dur(now - start), "seconds": round(now - start)})
        else:
            self._fails += 1
            self._first_fail = self._first_fail or now
            status = "offline" if self._fails >= 2 else (prev if prev != "unknown" else "offline")
            if self._fails == 2 and self._outage_id is None:
                scope = "lan" if gw_ok is False else "internet"
                self._outage_id = self.db.open_outage(self._first_fail, scope)
                self._outage_scope = scope
                await self.notifier.alert("gateway_down" if scope == "lan" else "internet_down", "critical",
                                          None, {"scope": scope})
        if status != prev:
            self.state["since"] = now
        self.state.update(status=status, latency=round(lat, 1) if lat else None, gw_ok=gw_ok, dns_ok=dns_ok,
                          last=now, loss=loss)
        await self.hub.broadcast("monitor", self.state)
        return self.state

    async def loop(self) -> None:
        # Close any outage left open by a previous crash/shutdown.
        for o in self.db.outages(0):
            if o["end"] is None:
                self.db.close_outage(o["id"], time.time())
        prune_at = 0.0
        while True:
            try:
                await self.check()
            except Exception:  # noqa: BLE001
                pass
            if time.time() > prune_at:
                self.db.prune()
                prune_at = time.time() + 3600
            interval = int(self.db.get_setting("monitor_interval_s", 15) or 15)
            await asyncio.sleep(max(5, interval) if self.state["status"] != "offline" else 5)

    async def bandwidth_loop(self) -> None:
        last = None
        while True:
            await asyncio.sleep(1)
            iface = (self.engine.net or {}).get("interface")
            try:
                counters = psutil.net_io_counters(pernic=True)
                c = counters.get(iface) if iface else None
                c = c or psutil.net_io_counters()
            except Exception:  # noqa: BLE001
                continue
            now = time.time()
            if last:
                dt = max(0.001, now - last[0])
                self.bandwidth = {"rx": max(0.0, (c.bytes_recv - last[1]) * 8 / dt / 1e6),
                                  "tx": max(0.0, (c.bytes_sent - last[2]) * 8 / dt / 1e6), "ts": now}
                if self.hub.clients:
                    await self.hub.broadcast("bandwidth", self.bandwidth)
            last = (now, c.bytes_recv, c.bytes_sent)

    def summary(self, hours: int = 24) -> dict:
        since = time.time() - hours * 3600
        samples = self.db.samples(since)
        buckets = 96
        span = hours * 3600 / buckets
        series = []
        for i in range(buckets):
            b0 = since + i * span
            chunk = [x for x in samples if b0 <= x["ts"] < b0 + span]
            if not chunk:
                series.append({"ts": b0, "latency": None, "loss": None})
                continue
            lats = [x["latency"] for x in chunk if x["latency"] is not None]
            series.append({"ts": b0, "latency": round(sum(lats) / len(lats), 1) if lats else None,
                           "loss": round(100 * sum(1 for x in chunk if not x["ok"]) / len(chunk), 1)})
        total = len(samples)
        ok = sum(1 for x in samples if x["ok"])
        lats = sorted(x["latency"] for x in samples if x["latency"] is not None)
        outages = self.db.outages(since)
        for o in outages:
            o["duration"] = (o["end"] or time.time()) - o["start"]
        return {
            "hours": hours, "uptime": round(100 * ok / total, 2) if total else None, "samples": total,
            "latency_avg": round(sum(lats) / len(lats), 1) if lats else None,
            "latency_p95": round(lats[int(len(lats) * 0.95) - 1], 1) if lats else None,
            "series": series, "outages": outages, "state": self.state,
        }


def _fmt_dur(sec: float) -> str:
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m {sec % 60}s"
    return f"{sec // 3600}h {(sec % 3600) // 60}m"
