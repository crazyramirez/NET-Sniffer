"""Capture README screenshots from a demo instance (fictional network data) with headless Chrome.

Uses the Chrome DevTools Protocol so phone shots get a real 390 px mobile viewport
(plain --window-size cannot go below Chrome's minimum window width).

    python scripts/screenshots.py [--lang en]
Output: docs/assets/screens/*.webp
"""
from __future__ import annotations

import argparse
import base64
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

import httpx
from PIL import Image
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "assets" / "screens"
PORT, CDP_PORT = 18999, 9333
TOKEN = "demo-screenshots-token"
CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "chromium", "chromium-browser",
]
# name, route, theme, (width, height), mobile
SHOTS = [
    ("dashboard-dark", "#/dashboard", "dark", (1440, 900), False),
    ("devices-dark", "#/devices", "dark", (1440, 900), False),
    ("device-detail-dark", "#/devices/f0%3A18%3A98%3A5e%3A7a%3A01", "dark", (1440, 900), False),
    ("security-dark", "#/security", "dark", (1440, 900), False),
    ("dashboard-light", "#/dashboard", "light", (1440, 900), False),
    ("speed-light", "#/speed", "light", (1440, 900), False),
    ("monitor-light", "#/monitor", "light", (1440, 900), False),
    ("notifications-light", "#/settings/notifications", "light", (1440, 900), False),
    ("mobile-dashboard-dark", "#/dashboard", "dark", (390, 844), True),
    ("mobile-devices-light", "#/devices", "light", (390, 844), True),
    ("mobile-security-dark", "#/security", "dark", (390, 844), True),
    ("mobile-speed-light", "#/speed", "light", (390, 844), True),
]


def chrome() -> str:
    for c in CHROME:
        if Path(c).exists() or shutil.which(c):
            return c
    sys.exit("Chrome/Chromium not found")


class CDP:
    def __init__(self, ws_url: str) -> None:
        self.ws = connect(ws_url, max_size=64 * 1024 * 1024, open_timeout=20).__enter__()
        self.ids = itertools.count(1)

    def call(self, method: str, **params):
        mid = next(self.ids)
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv(timeout=60))
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def close(self) -> None:
        self.ws.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="en")
    ap.add_argument("--only", default="", help="comma-separated shot names")
    a = ap.parse_args()
    data = Path(tempfile.mkdtemp(prefix="ns-demo-"))
    env = dict(os.environ, NETSNIFFER_DEMO="1", NETSNIFFER_DATA=str(data), NETSNIFFER_LAUNCH_TOKEN=TOKEN)
    srv = subprocess.Popen([sys.executable, "-m", "netsniffer", "--headless", "--host", "127.0.0.1", "--port", str(PORT)],
                           cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    browser = subprocess.Popen([chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                                f"--remote-debugging-port={CDP_PORT}", "--remote-allow-origins=*",
                                f"--user-data-dir={data / 'chrome'}", "about:blank"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{PORT}"
    try:
        client = httpx.Client(base_url=base, timeout=20, follow_redirects=False)
        for _ in range(60):
            try:
                client.get(f"/launch?token={TOKEN}")
                if client.get("/api/state").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        for _ in range(40):
            try:
                httpx.get(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2)
                break
            except httpx.HTTPError:
                time.sleep(0.5)
        time.sleep(4)  # let the monitor collect a couple of live samples
        OUT.mkdir(parents=True, exist_ok=True)
        only = {s for s in a.only.split(",") if s}
        for name, route, theme, (w, h), mobile in SHOTS:
            if only and name not in only:
                continue
            client.put("/api/settings", json={"theme": theme, "language": a.lang})
            target = httpx.put(f"http://127.0.0.1:{CDP_PORT}/json/new?about:blank", timeout=10).json()
            cdp = CDP(target["webSocketDebuggerUrl"])
            try:
                cdp.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=2 if not mobile else 3,
                         mobile=mobile, screenWidth=w, screenHeight=h)
                if mobile:
                    cdp.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
                cdp.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": theme}])
                cdp.call("Page.enable")
                url = f"{base}/launch?token={TOKEN}&next={urllib.parse.quote(route, safe='')}"
                cdp.call("Page.navigate", url=url)
                time.sleep(6)
                shot = cdp.call("Page.captureScreenshot", format="png")
                overflow = cdp.call("Runtime.evaluate", expression="document.documentElement.scrollWidth - innerWidth",
                                    returnByValue=True)["result"].get("value")
            finally:
                cdp.close()
                httpx.get(f"http://127.0.0.1:{CDP_PORT}/json/close/{target['id']}", timeout=5)
            img = Image.open(io.BytesIO(base64.b64decode(shot["data"]))).convert("RGB")
            if mobile:
                img = img.resize((w * 2, h * 2), Image.LANCZOS)
            out = OUT / f"{name}.webp"
            img.save(out, "WEBP", quality=88, method=6)
            print(f"{out.relative_to(ROOT)}  {out.stat().st_size // 1024} KiB  horizontal overflow: {overflow}px")
    finally:
        for p in (browser, srv):
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        shutil.rmtree(data, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
