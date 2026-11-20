"""Self-update from GitHub Releases. Only the latest release exists; old binaries are deleted locally."""
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
import time
from pathlib import Path
from typing import Callable

import httpx

from . import __version__
from .config import FROZEN, IS_MAC, IS_WINDOWS, REPO

log = logging.getLogger("netsniffer.updater")
CHECK_EVERY = 6 * 3600


def arch() -> str:
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64", "armv8l") else "x64"


def asset_name() -> str:
    if IS_WINDOWS:
        return "NETSniffer-Windows-x64.exe"
    if IS_MAC:
        return f"NETSniffer-macOS-{arch()}.zip"
    return f"NETSniffer-Linux-{arch()}"


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.split("-")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def current_target() -> Path:
    exe = Path(sys.executable).resolve()
    if IS_MAC and ".app/Contents/MacOS" in str(exe):
        return exe.parents[2]
    return exe


def cleanup_previous() -> None:
    """Remove the previous version left behind by an update (never keep old versions)."""
    if not FROZEN:
        return
    target = current_target()
    old = target.with_name(target.name + ".old")
    for p in (old, target.with_name(target.name + ".new"), target.parent / ".netsniffer-update"):
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
        target = current_target()
        work = target.parent / ".netsniffer-update"
        work.mkdir(exist_ok=True)
        dest = work / self._asset["name"]
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
            shutil.rmtree(work, ignore_errors=True)
            self.state.update(status="error", error=str(exc)[:200])
            await self._emit()
            return False

    def install(self) -> bool:
        """Swap binaries in place. Safe to call while running; the new version starts on next launch."""
        if not (FROZEN and self._download and self._download.exists()):
            return False
        target = current_target()
        old = target.with_name(target.name + ".old")
        try:
            if old.exists():
                shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink()
            if IS_MAC:
                extract = self._download.parent / "x"
                subprocess.run(["ditto", "-x", "-k", str(self._download), str(extract)], check=True)
                new_app = next(extract.glob("*.app"))
                subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(new_app)], check=False)
                os.rename(target, old)
                shutil.move(str(new_app), str(target))
            else:
                if not IS_WINDOWS:
                    self._download.chmod(0o755)
                os.replace(target, old)  # renaming a running executable is allowed on Windows/Unix
                shutil.move(str(self._download), str(target))
            shutil.rmtree(self._download.parent, ignore_errors=True)
            if not IS_WINDOWS:
                old_path = old  # Unix: the running inode stays valid; delete now
                shutil.rmtree(old_path, ignore_errors=True) if old_path.is_dir() else old_path.unlink(missing_ok=True)
            self._download = None
            self.state.update(status="installed")
            return True
        except Exception as exc:  # noqa: BLE001
            log.exception("install failed")
            if old.exists() and not target.exists():
                os.rename(old, target)
            self.state.update(status="error", error=str(exc)[:200])
            return False

    def relaunch(self) -> None:
        target = current_target()
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        args = [a for a in sys.argv[1:] if a != "--updated"] + ["--updated"]
        if IS_MAC:
            subprocess.Popen(["open", "-n", str(target), "--args", *args], env=env)
        elif IS_WINDOWS:
            subprocess.Popen([str(target), *args], env=env, close_fds=True,
                             creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | NEW_PROCESS_GROUP
        else:
            subprocess.Popen([str(target), *args], env=env, close_fds=True, start_new_session=True)

    async def apply_now(self) -> bool:
        if self.state["status"] != "ready" and not await self.download():
            return False
        if not self.install():
            return False
        # Under systemd (Raspberry Pi service) just exit: Restart=always starts the new binary.
        if not (self.headless and os.environ.get("INVOCATION_ID")):
            self.relaunch()
        if self.shutdown:
            asyncio.get_running_loop().call_later(0.8, self.shutdown)
        return True

    def install_on_exit(self) -> None:
        if self.state.get("status") == "ready":
            self.install()

    async def loop(self) -> None:
        await asyncio.sleep(4)
        while True:
            await self.check()
            if self.state["available"] and FROZEN and self.db.get_setting("auto_update", True):
                if await self.download() and self.headless:
                    await self.apply_now()
            await asyncio.sleep(CHECK_EVERY)
