"""Paths, defaults and runtime flags."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import GITHUB_REPO, __app_id__

FROZEN = bool(getattr(sys, "frozen", False))
IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

PACKAGE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "netsniffer" \
    if FROZEN else Path(__file__).resolve().parent
WEB_DIR = PACKAGE_DIR / "web"
DATA_FILES_DIR = PACKAGE_DIR / "data"
LOCALES_DIR = WEB_DIR / "locales"

REPO = os.environ.get("NETSNIFFER_REPO", GITHUB_REPO)
SUPPORTED_LANGUAGES = ["es", "en", "fr", "de", "it", "zh", "ja"]


def data_dir() -> Path:
    override = os.environ.get("NETSNIFFER_DATA")
    if override:
        p = Path(override)
    elif IS_WINDOWS:
        p = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / __app_id__
    elif IS_MAC:
        p = Path.home() / "Library" / "Application Support" / __app_id__
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "netsniffer"
    p.mkdir(parents=True, exist_ok=True)
    return p


DEFAULT_SETTINGS: dict = {
    "language": "auto",
    "theme": "system",
    "auto_scan": True,
    "scan_interval_min": 15,
    "watcher": True,
    "monitor_interval_s": 15,
    "port_profile": "quick",
    # background / desktop integration
    "background": True,
    "launch_at_login": False,
    # notifications (each one can be switched on/off)
    "notify_enabled": True,
    "notify_desktop": True,
    "notify_sound": True,
    "notify_new_device": True,
    "notify_unknown_online": True,
    "notify_device_online": False,
    "notify_device_offline": False,
    "notify_favorites": True,
    "notify_ip_change": False,
    "notify_internet": True,
    "notify_security": True,
    "notify_camera": True,
    "notify_quiet": False,
    "notify_quiet_start": "23:00",
    "notify_quiet_end": "07:00",
    "notify_ntfy_url": "",
    "notify_telegram_token": "",
    "notify_telegram_chat": "",
    "notify_webhook_url": "",
    "remote_enabled": False,
    "remote_port": 8765,
    "block_backend": "none",
    "block_host": "",
    "block_port": 22,
    "block_user": "root",
    "block_password": "",
    "block_firewall": "nft",
    "auto_update": True,
    "public_ip_lookup": True,
    "onboarded": False,
}

# Settings never sent back to clients in clear text.
SECRET_SETTINGS = {"block_password", "notify_telegram_token"}
