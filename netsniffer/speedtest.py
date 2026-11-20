"""Internet speed test against Cloudflare's public speed test edge (latency, jitter, download, upload)."""
from __future__ import annotations

import asyncio
import os
import re
import statistics
import time
from collections import deque
from typing import Awaitable, Callable

import httpx

from .net.interfaces import CF_HEADERS, public_info

BASE = "https://speed.cloudflare.com"
Progress = Callable[[dict], Awaitable[None]]


class SpeedTest:
    def __init__(self) -> None:
        self.running = False
        self._payload = os.urandom(1 << 20)

    @staticmethod
    def _client(streams: int) -> httpx.AsyncClient:
        limits = httpx.Limits(max_connections=streams + 2, max_keepalive_connections=streams + 2)
        return httpx.AsyncClient(timeout=httpx.Timeout(15, connect=8), limits=limits, headers=CF_HEADERS,
                                 http2=False)

    async def _latency(self, client: httpx.AsyncClient, progress: Progress) -> tuple[float, float, float]:
        samples: list[float] = []
        lost = 0
        for i in range(14):
            t = time.perf_counter()
            try:
                r = await client.get(f"{BASE}/__down", params={"bytes": 0})
                elapsed = (time.perf_counter() - t) * 1000
                # subtract the edge/worker processing time reported via Server-Timing
                timing = r.headers.get("server-timing", "")
                server = sum(float(x) for x in re.findall(r"(?:cfRequestDuration|cfSpeedEdge|cfSpeedWorker)"
                                                           r";dur=([\d.]+)", timing))
                if i > 1:  # first requests include TCP+TLS handshakes
                    samples.append(max(0.5, elapsed - server))
            except httpx.HTTPError:
                lost += 1
            await progress({"phase": "ping", "progress": (i + 1) / 14,
                            "ping": round(min(samples), 1) if samples else None})
        if not samples:
            raise RuntimeError("speedtest_unreachable")
        ping = statistics.median(samples)
        jitter = statistics.mean(abs(a - b) for a, b in zip(samples, samples[1:])) if len(samples) > 1 else 0.0
        return round(ping, 1), round(jitter, 1), round(100 * lost / 14, 1)

    async def _transfer(self, client: httpx.AsyncClient, direction: str, streams: int, duration: float,
                        progress: Progress) -> float:
        total = 0
        stop = time.perf_counter() + duration
        window: deque[tuple[float, int]] = deque()
        start = time.perf_counter()
        warmup = start + min(1.5, duration * 0.15)
        counted_from = 0

        async def down_worker() -> None:
            nonlocal total
            while time.perf_counter() < stop:
                try:
                    async with client.stream("GET", f"{BASE}/__down", params={"bytes": 50_000_000}) as r:
                        async for chunk in r.aiter_raw(1 << 16):
                            total += len(chunk)
                            if time.perf_counter() >= stop:
                                return
                except httpx.HTTPError:
                    await asyncio.sleep(0.2)

        async def up_worker() -> None:
            payload = self._payload

            async def body():
                nonlocal total
                sent = 0
                while sent < 16 * len(payload) and time.perf_counter() < stop:
                    for i in range(0, len(payload), 1 << 16):
                        piece = payload[i:i + (1 << 16)]
                        sent += len(piece)
                        total += len(piece)
                        yield piece
                    await asyncio.sleep(0)

            while time.perf_counter() < stop:
                try:
                    await client.post(f"{BASE}/__up", content=body(),
                                      headers={"Content-Type": "application/octet-stream"})
                except httpx.HTTPError:
                    await asyncio.sleep(0.2)

        worker = down_worker if direction == "download" else up_worker
        tasks = [asyncio.create_task(worker()) for _ in range(streams)]
        last_report = 0.0
        while time.perf_counter() < stop:
            await asyncio.sleep(0.2)
            now = time.perf_counter()
            if counted_from == 0 and now >= warmup:
                counted_from = total
                warm_ts = now
            window.append((now, total))
            while window and now - window[0][0] > 1.5:
                window.popleft()
            if len(window) > 1:
                dt = window[-1][0] - window[0][0]
                current = (window[-1][1] - window[0][1]) * 8 / dt / 1e6 if dt > 0 else 0
            else:
                current = 0
            if now - last_report >= 0.2:
                last_report = now
                await progress({"phase": direction, "progress": min(1.0, (now - start) / duration),
                                "speed": round(current, 2)})
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        end = time.perf_counter()
        if counted_from == 0:
            return round(total * 8 / max(0.001, end - start) / 1e6, 2)
        return round((total - counted_from) * 8 / max(0.001, end - warm_ts) / 1e6, 2)

    async def run(self, progress: Progress) -> dict:
        if self.running:
            raise RuntimeError("speedtest_running")
        self.running = True
        try:
            await progress({"phase": "connect", "progress": 0})
            meta = await public_info(force=True) or {}
            async with self._client(8) as client:
                ping, jitter, loss = await self._latency(client, progress)
                down = await self._transfer(client, "download", 6, 10.0, progress)
                up = await self._transfer(client, "upload", 4, 8.0, progress)
            result = {"ts": time.time(), "ping": ping, "jitter": jitter, "loss": loss, "download": down,
                      "upload": up, "isp": meta.get("isp"), "ip": meta.get("ip"),
                      "server": f"Cloudflare · {meta.get('colo')}" if meta.get("colo") else "Cloudflare"}
            await progress({"phase": "done", "progress": 1, "result": result})
            return result
        finally:
            self.running = False
