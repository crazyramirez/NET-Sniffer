"""Server-side translations (notifications, reports). Shares locale files with the web UI."""
from __future__ import annotations

import json
import locale
import os
import re
import subprocess
from functools import lru_cache

from .config import IS_MAC, IS_WINDOWS, LOCALES_DIR, SUPPORTED_LANGUAGES


@lru_cache(maxsize=16)
def _load(lang: str) -> dict:
    try:
        return json.loads((LOCALES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _lookup(data: dict, key: str):
    cur = data
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur if isinstance(cur, str) else None


def tr(lang: str, key: str, **params) -> str:
    text = _lookup(_load(lang), key) or _lookup(_load("en"), key) or key
    return re.sub(r"\{(\w+)\}", lambda m: str(params.get(m.group(1), m.group(0))), text)


def match_language(tag: str | None) -> str | None:
    if not tag:
        return None
    base = tag.replace("_", "-").split("-")[0].lower()
    return base if base in SUPPORTED_LANGUAGES else None


def os_language() -> str:
    tag = None
    try:
        if IS_WINDOWS:
            import ctypes
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            tag = locale.windows_locale.get(lcid)
        elif IS_MAC:
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True,
                                 timeout=3).stdout
            m = re.search(r'"?([a-zA-Z]{2}(?:[-_][\w]+)?)"?', out)
            tag = m.group(1) if m else None
        if not tag:
            tag = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG")
        if not tag:
            tag = locale.getlocale()[0]
    except Exception:  # noqa: BLE001
        tag = None
    return match_language(tag) or "en"


def resolve(setting: str | None) -> str:
    if setting and setting != "auto" and setting in SUPPORTED_LANGUAGES:
        return setting
    return os_language()
