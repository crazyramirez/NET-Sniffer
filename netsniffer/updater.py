"""Self-update from GitHub Releases. Only the latest release exists; previous versions are removed locally.

Windows: downloads the new installer and runs it silently (per-user install, no admin) → app relaunches.
macOS:   downloads the .dmg, copies the new NETSniffer.app over the current one.
Linux:   replaces the single binary in place, or installs the .deb (pkexec) for system-wide installs.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

import httpx

from . import __version__
from .config import FROZEN, IS_MAC, IS_WINDOWS, REPO

log = logging.getLogger("netsniffer.updater")
CHECK_EVERY = 6 * 3600
WORK = Path(tempfile.gettempdir()) / "NETSniffer-update"


def arch() -> str:
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64", "armv8l") else "x64"


def current_target() -> Path:
    exe = Path(sys.executable).resolve()
    if IS_MAC and ".app/Contents/MacOS" in str(exe):
        return exe.parents[2]
    return exe


def linux_writable() -> bool:
    t = current_target()
    return os.access(t, os.W_OK) and os.access(t.parent, os.W_OK)


def asset_name() -> str:
    if IS_WINDOWS:
        return "NETSniffer-Setup-Windows-x64.exe"
    if IS_MAC:
        return f"NETSniffer-macOS-{arch()}.dmg"
    return f"NETSniffer-Linux-{arch()}" + ("" if not FROZEN or linux_writable() else ".deb")


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.split("-")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def cleanup_previous() -> None:
    """Remove leftovers of a previous update (never keep old versions)."""
    if not FROZEN:
        return
    target = current_target()
    for p in (target.with_name(target.name + ".old"), target.with_name(target.name + ".new"), WORK):
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.exists():
                p.unlink()
        except OSError:
            pass


class Updater:
    def __init__(self, db, hub) -> None:
        self.db, self.hub = db, hub
        self.state: dict = {"current": __version__, "latest": None, "available": False, "status": "idle",
                            "progress": 0, "notes": "", "error": None, "url": None, "published": None,
                            "can_apply": FROZEN, "repo": REPO, "checked": None}
        self._asset: dict | None = None
        self._download: Path | None = None
        self.shutdown: Callable[[], None] | None = None
        self.headless = False

    async def _emit(self) -> None:
        await self.hub.broadcast("update", self.state)

    async def check(self) -> dict:
        self.state.update(status="checking", error=None)
        await self._emit()
        try:
            async with httpx.AsyncClient(timeout=10, headers={"Accept": "application/vnd.github+json",
                                                              "User-Agent": "NETSniffer-Updater"}) as c:
                r = await c.get(f"https://api.github.com/repos/{REPO}/releases/latest")
            if r.status_code == 404:
                self.state.update(status="uptodate", latest=None, available=False, checked=time.time())
                return self.state
            r.raise_for_status()
            rel = r.json()
            latest = rel.get("tag_name", "").lstrip("v")
            newer = parse_version(latest) > parse_version(__version__)
            self._asset = next((a for a in rel.get("assets", []) if a.get("name") == asset_name()), None)
            self.state.update(latest=latest, available=newer, notes=(rel.get("body") or "")[:4000],
                              url=rel.get("html_url"), published=rel.get("published_at"), checked=time.time(),
                              status="available" if newer else "uptodate")
            if newer and not self._asset:
                self.state["status"] = "no_asset"
        except (httpx.HTTPError, ValueError) as exc:
            self.state.update(status="error", error=str(exc)[:200])
        await self._emit()
        return self.state

    async def download(self) -> bool:
        if not (FROZEN and self._asset and self.state["available"]):
            return False
        shutil.rmtree(WORK, ignore_errors=True)
        WORK.mkdir(parents=True, exist_ok=True)
        dest = WORK / self._asset["name"]
        self.state.update(status="downloading", progress=0)
        await self._emit()
        h = hashlib.sha256()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=60), follow_redirects=True,
                                         headers={"Accept": "application/octet-stream",
                                                  "User-Agent": "NETSniffer-Updater"}) as c:
                async with c.stream("GET", self._asset["browser_download_url"]) as r:
                    r.raise_for_status()
                    size = int(r.headers.get("content-length") or self._asset.get("size") or 0)
                    got, last = 0, 0.0
                    with open(dest, "wb") as fh:
                        async for chunk in r.aiter_bytes(1 << 16):
                            fh.write(chunk)
                            h.update(chunk)
                            got += len(chunk)
                            if size and time.time() - last > 0.3:
                                last = time.time()
                                self.state["progress"] = round(got / size, 3)
                                await self._emit()
            digest = (self._asset.get("digest") or "").removeprefix("sha256:")
            if digest and digest.lower() != h.hexdigest():
                raise ValueError("checksum_mismatch")
            self._download = dest
            self.state.update(status="ready", progress=1)
            await self._emit()
            return True
        except (httpx.HTTPError, OSError, ValueError) as exc:
            shutil.rmtree(WORK, ignore_errors=True)
            self.state.update(status="error", error=str(exc)[:200])
            await self._emit()
            return False

    # ------------------------------------------------------------------ install
    def install(self, relaunch: bool) -> bool:
        """Install the downloaded package. Returns True when the app must now exit."""
        if not (FROZEN and self._download and self._download.exists()):
            return False
        try:
            if IS_WINDOWS:
                # the installer closes the running app, replaces the files and (optionally) restarts it
                subprocess.Popen([str(self._download), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                  "/CLOSEAPPLICATIONS", f"/RELAUNCH={1 if relaunch else 0}"],
                                 close_fds=True, creationflags=0x00000008 | 0x00000200)
            elif IS_MAC:
                self._install_mac()
            elif self._download.suffix == ".deb":
                subprocess.run(["pkexec", "dpkg", "-i", str(self._download)], check=True, timeout=600)
            else:
                target = current_target()
                old = target.with_name(target.name + ".old")
                self._download.chmod(0o755)
                os.replace(target, old)  # the running inode stays valid on Unix
                shutil.move(str(self._download), str(target))
                old.unlink(missing_ok=True)
            self._download = None
            self.state.update(status="installed")
            if relaunch and not IS_WINDOWS:
                self.relaunch()
            return True
        except Exception as exc:  # noqa: BLE001
            log.exception("install failed")
            self.state.update(status="error", error=str(exc)[:200])
            return False

    def _install_mac(self) -> None:
        target = current_target()
        mount = WORK / "mnt"
        mount.mkdir(exist_ok=True)
        subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount),
                        str(self._download)], check=True, timeout=120)
        try:
            new_app = next(mount.glob("*.app"))
            staged = WORK / new_app.name
            subprocess.run(["ditto", str(new_app), str(staged)], check=True, timeout=300)
        finally:
            subprocess.run(["hdiutil", "detach", str(mount), "-force"], check=False, timeout=60)
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(staged)], check=False)
        old = target.with_name(target.name + ".old")
        shutil.rmtree(old, ignore_errors=True)
        os.rename(target, old)
        shutil.move(str(staged), str(target))
        shutil.rmtree(old, ignore_errors=True)

    def relaunch(self) -> None:
        target = current_target()
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        args = [a for a in sys.argv[1:] if a not in ("--updated", "--background")] + ["--updated"]
        if IS_MAC:
            subprocess.Popen(["open", "-n", str(target), "--args", *args], env=env)
        else:
            subprocess.Popen([str(target), *args], env=env, close_fds=True, start_new_session=True)

    async def apply_now(self) -> bool:
        if self.state["status"] != "ready" and not await self.download():
            return False
        # Under systemd (Raspberry Pi service) don't relaunch: Restart=always starts the new binary.
        relaunch = not (self.headless and os.environ.get("INVOCATION_ID"))
        if not self.install(relaunch=relaunch):
            return False
        if self.shutdown:
            asyncio.get_running_loop().call_later(0.8, self.shutdown)
        return True

    def install_on_exit(self) -> None:
        if self.state.get("status") == "ready":
            self.install(relaunch=False)

    async def loop(self) -> None:
        await asyncio.sleep(4)
        while True:
            await self.check()
            if self.state["available"] and FROZEN and self.db.get_setting("auto_update", True):
                if await self.download() and self.headless:
                    await self.apply_now()
            await asyncio.sleep(CHECK_EVERY)
