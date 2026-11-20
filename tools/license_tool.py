"""Publisher tool: create the signing key pair and issue NET Sniffer Pro license keys.

    python tools/license_tool.py init                 # once: creates ~/.netsniffer/license_private.pem
    python tools/license_tool.py issue --name "Jane" --email jane@example.com --days 365
    python tools/license_tool.py verify NS1.xxxxx.yyyy

The private key is stored OUTSIDE the repository. Back it up safely: losing it means you can no longer
issue keys that existing app builds accept; leaking it lets anyone mint licenses.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import re
import sys
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parent.parent
KEY_DIR = Path.home() / ".netsniffer"
PRIVATE = KEY_DIR / "license_private.pem"
LICENSING = ROOT / "netsniffer" / "licensing.py"


def b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def load_private() -> Ed25519PrivateKey:
    return serialization.load_pem_private_key(PRIVATE.read_bytes(), password=None)  # type: ignore[return-value]


def cmd_init(_: argparse.Namespace) -> int:
    if PRIVATE.exists():
        print(f"Key already exists: {PRIVATE}")
    else:
        KEY_DIR.mkdir(parents=True, exist_ok=True)
        key = Ed25519PrivateKey.generate()
        PRIVATE.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
        print(f"Created {PRIVATE}  (BACK IT UP)")
    pub = load_private().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    pub_b64 = base64.b64encode(pub).decode()
    src = LICENSING.read_text(encoding="utf-8")
    src = re.sub(r'PUBLIC_KEY_B64 = "[^"]*"', f'PUBLIC_KEY_B64 = "{pub_b64}"', src)
    LICENSING.write_text(src, encoding="utf-8")
    print(f"Embedded public key in {LICENSING.relative_to(ROOT)}: {pub_b64}")
    return 0


def cmd_issue(a: argparse.Namespace) -> int:
    today = dt.date.today()
    payload = {
        "id": uuid.uuid4().hex[:12], "name": a.name, "email": a.email, "plan": "pro",
        "issued": today.isoformat(),
        "expires": (today + dt.timedelta(days=a.days)).isoformat() if a.days else None,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    sig = load_private().sign(raw)
    print(f"NS1.{b64e(raw)}.{b64e(sig)}")
    return 0


def cmd_verify(a: argparse.Namespace) -> int:
    sys.path.insert(0, str(ROOT))
    from netsniffer.licensing import verify_key
    print(json.dumps(verify_key(a.key), indent=2) if verify_key(a.key) else "INVALID")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    i = sub.add_parser("issue")
    i.add_argument("--name", required=True)
    i.add_argument("--email", required=True)
    i.add_argument("--days", type=int, default=365, help="0 = lifetime")
    i.set_defaults(fn=cmd_issue)
    v = sub.add_parser("verify")
    v.add_argument("key")
    v.set_defaults(fn=cmd_verify)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
