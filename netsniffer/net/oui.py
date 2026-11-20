"""MAC address vendor lookup (IEEE MA-L / MA-M / MA-S registries)."""
from __future__ import annotations

import gzip
import json
import re
from functools import lru_cache

from ..config import DATA_FILES_DIR

_SUFFIXES = re.compile(
    r"[,.]?\s*(co\.?,?\s*ltd\.?|corporation|corp\.?|inc\.?|incorporated|limited|ltd\.?|llc|gmbh|s\.?a\.?|"
    r"s\.?r\.?l\.?|b\.?v\.?|ag|oy|ab|a/s|pte\.?|pty\.?|technologies|technology|electronics|international|"
    r"holdings?|company|group|co\.?)\s*$", re.I)

_ALIASES = {
    "tp-link": "TP-Link", "hewlett packard": "HP", "hon hai": "Foxconn", "samsung": "Samsung",
    "apple": "Apple", "google": "Google", "amazon": "Amazon", "huawei": "Huawei", "xiaomi": "Xiaomi",
    "espressif": "Espressif", "raspberry pi": "Raspberry Pi", "intel": "Intel", "microsoft": "Microsoft",
    "sony interactive": "Sony Interactive", "nintendo": "Nintendo", "lg electronics": "LG",
    "murata": "Murata", "azurewave": "AzureWave", "liteon": "Lite-On", "realtek": "Realtek",
    "hangzhou hikvision": "Hikvision", "zhejiang dahua": "Dahua", "ubiquiti": "Ubiquiti",
    "synology": "Synology", "sonos": "Sonos", "signify": "Philips Hue", "philips lighting": "Philips Hue",
    "avm": "AVM (FRITZ!)", "netgear": "Netgear", "asustek": "ASUS", "d-link": "D-Link",
    "zte": "ZTE", "sagemcom": "Sagemcom", "askey": "Askey", "mitrastar": "MitraStar", "arcadyan": "Arcadyan",
    "tuya": "Tuya", "shenzhen bilian": "Bilian", "roku": "Roku", "nvidia": "NVIDIA", "dell": "Dell",
    "lenovo": "Lenovo", "oneplus": "OnePlus", "guangdong oppo": "OPPO", "vivo mobile": "vivo",
    "motorola": "Motorola", "texas instruments": "Texas Instruments", "seiko epson": "Epson",
    "brother": "Brother", "canon": "Canon", "wyze": "Wyze", "reolink": "Reolink", "ring": "Ring",
    "valve": "Valve", "bose": "Bose", "withings": "Withings", "ecobee": "ecobee", "nest labs": "Google Nest",
    "itead": "Sonoff (ITEAD)", "shelly": "Shelly", "allterco": "Shelly", "qnap": "QNAP",
    "western digital": "Western Digital", "ezviz": "EZVIZ", "hisense": "Hisense", "tcl": "TCL",
}


@lru_cache(maxsize=1)
def _db() -> dict[str, dict[str, str]]:
    path = DATA_FILES_DIR / "oui.json.gz"
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"24": {}, "28": {}, "36": {}}


def clean_vendor(name: str) -> str:
    low = name.lower()
    for key, alias in _ALIASES.items():
        if low.startswith(key) or f" {key}" in low[:40] and key in ("tp-link",):
            return alias
    prev = None
    name = name.strip()
    while prev != name:
        prev = name
        name = _SUFFIXES.sub("", name).strip(" ,.")
    return name[:40] if name else prev


def lookup(mac: str | None) -> str | None:
    if not mac:
        return None
    hexs = re.sub(r"[^0-9a-f]", "", mac.lower())
    if len(hexs) != 12:
        return None
    db = _db()
    for bits in ("36", "28", "24"):
        hit = db.get(bits, {}).get(hexs[: int(bits) // 4])
        if hit:
            return clean_vendor(hit)
    return None


def raw_lookup(mac: str | None) -> str | None:
    if not mac:
        return None
    hexs = re.sub(r"[^0-9a-f]", "", mac.lower())
    db = _db()
    for bits in ("36", "28", "24"):
        hit = db.get(bits, {}).get(hexs[: int(bits) // 4])
        if hit:
            return hit
    return None
