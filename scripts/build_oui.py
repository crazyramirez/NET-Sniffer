"""Download the latest IEEE OUI registry (Wireshark 'manuf' mirror) into netsniffer/data/oui.json.gz."""
from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

import httpx

URL = "https://www.wireshark.org/download/automated/data/manuf"
OUT = Path(__file__).resolve().parent.parent / "netsniffer" / "data" / "oui.json.gz"


def main() -> int:
    text = httpx.get(URL, timeout=120, follow_redirects=True).text
    db: dict[str, dict[str, str]] = {"24": {}, "28": {}, "36": {}}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        prefix = parts[0].strip()
        name = (parts[2] if len(parts) > 2 and parts[2].strip() else parts[1]).strip()
        bits = 24
        if "/" in prefix:
            prefix, b = prefix.split("/")
            bits = int(b)
        hexs = re.sub(r"[^0-9A-Fa-f]", "", prefix).lower()
        if bits not in (24, 28, 36):
            continue
        db[str(bits)][hexs[: bits // 4]] = name
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(db, fh, separators=(",", ":"), ensure_ascii=False)
    print(f"OUI entries: {sum(len(v) for v in db.values())} -> {OUT} ({OUT.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
