"""Desktop integration: system tray, background mode, single-instance wake-up and launch at login."""
from __future__ import annotations

import logging
import os
import plistlib
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from . import __app_name__, i18n
from .config import FROZEN, IS_MAC, IS_WINDOWS, PACKAGE_DIR

log = logging.getLogger("netsniffer.desktop")
AUTOSTART_ID = "NETSniffer"


# ---------------------------------------------------------------------------- launch at login
def _launch_command() -> list[str]:
    if FROZEN:
        exe = Path(sys.executable).resolve()
        return [str(exe), "--background"]
    return [sys.executable, "-m", "netsniffer", "--background"]


def _mac_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "app.netsniffer.desktop.plist"


def _linux_desktop() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / "netsniffer.desktop"


def set_autostart(enabled: bool) -> bool:
    cmd = _launch_command()
    try:
        if IS_WINDOWS:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                                 winreg.KEY_SET_VALUE)
            with key:
                if enabled:
                    winreg.SetValueEx(key, AUTOSTART_ID, 0, winreg.REG_SZ, subprocess.list2cmdline(cmd))
                else:
                    try:
                        winreg.DeleteValue(key, AUTOSTART_ID)
                    except FileNotFoundError:
                        pass
        elif IS_MAC:
            p = _mac_plist()
            if enabled:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(plistlib.dumps({"Label": "app.netsniffer.desktop", "ProgramArguments": cmd,
                                              "RunAtLoad": True, "ProcessType": "Interactive"}))
            else:
                p.unlink(missing_ok=True)
        else:
            p = _linux_desktop()
            if enabled:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("[Desktop Entry]\nType=Application\nName=NET Sniffer\n"
                             f"Exec={subprocess.list2cmdline(cmd)}\nX-GNOME-Autostart-enabled=true\n"
                             "NoDisplay=false\nTerminal=false\n", encoding="utf-8")
            else:
                p.unlink(missing_ok=True)
        return True
    except OSError as exc:
        log.warning("autostart change failed: %s", exc)
        return False


# ---------------------------------------------------------------------------- single instance
INSTANCE_PORT = 47391


def acquire_instance(wait: float = 0) -> socket.socket | None:
    """Bind the instance port. If another instance owns it, ask it to show its window and return None."""
    import time
    deadline = time.time() + wait
    while True:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if IS_WINDOWS:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            s.bind(("127.0.0.1", INSTANCE_PORT))
            s.listen(4)
            return s
        except OSError:
            s.close()
            if time.time() >= deadline:
                try:
                    with socket.create_connection(("127.0.0.1", INSTANCE_PORT), timeout=2) as c:
                        c.sendall(b"show\n")
                except OSError:
                    pass
                return None
            time.sleep(0.5)


def serve_instance(sock: socket.socket, on_show: Callable[[], None]) -> None:
    def loop() -> None:
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            with conn:
                try:
                    if conn.recv(16).strip() == b"show":
                        on_show()
                except OSError:
                    pass
    threading.Thread(target=loop, name="instance", daemon=True).start()


# ---------------------------------------------------------------------------- tray icon
class Tray:
    """System tray / menu bar icon. Optional: if the platform backend is missing, `available` stays False."""

    def __init__(self, lang: Callable[[], str], on_open, on_scan, on_toggle_notify, notify_enabled, on_quit) -> None:
        self.lang = lang
        self.on_open, self.on_scan, self.on_quit = on_open, on_scan, on_quit
        self.on_toggle_notify, self.notify_enabled = on_toggle_notify, notify_enabled
        self.icon = None
        self.available = False

    def _menu(self):
        import pystray
        t = lambda k: i18n.tr(self.lang(), k)  # noqa: E731
        return pystray.Menu(
            pystray.MenuItem(t("tray.open"), lambda: self.on_open(), default=True),
            pystray.MenuItem(t("tray.scan"), lambda: self.on_scan()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(t("tray.notifications"), lambda: self.on_toggle_notify(),
                             checked=lambda _item: self.notify_enabled()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(t("tray.quit"), lambda: self.on_quit()),
        )

    def start(self) -> bool:
        try:
            import pystray
            from PIL import Image
            img = Image.open(PACKAGE_DIR / "web" / "icon.png").convert("RGBA").resize((64, 64), Image.LANCZOS)
            self.icon = pystray.Icon("netsniffer", img, __app_name__, self._menu())
            if IS_MAC:
                self.icon.run_detached()  # integrates with the Cocoa loop started by pywebview
            else:
                threading.Thread(target=self.icon.run, name="tray", daemon=True).start()
            self.available = True
        except Exception as exc:  # noqa: BLE001 - tray is optional (e.g. Linux without appindicator)
            log.info("tray unavailable: %s", exc)
            self.available = False
        return self.available

    def refresh(self) -> None:
        if self.icon is not None:
            try:
                self.icon.menu = self._menu()
                self.icon.update_menu()
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:  # noqa: BLE001
                pass
