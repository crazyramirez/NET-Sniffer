"""Offline-verifiable subscription licenses (Ed25519 signatures) + 14-day Pro trial.

License key format:  NS1.<base64url(json payload)>.<base64url(signature)>
Payload: {"id": str, "name": str, "email": str, "plan": "pro", "issued": "YYYY-MM-DD", "expires": "YYYY-MM-DD"|null}
Keys are issued with tools/license_tool.py using the private key that never leaves the publisher's machine.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PUBLIC_KEY_B64 = "qCj5CZX5BKj2gi5a7I8N2XjnsFmilukwxiD8a1RBkEg="
TRIAL_DAYS = 14

FREE_FEATURES = {"scan", "devices", "speedtest", "monitor", "ports_quick", "wol", "alerts"}
PRO_FEATURES = {"audit", "cameras", "blocking", "parental", "remote", "notifications", "watcher",
                "custom_interval", "full_ports", "history", "export"}


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_key(key: str) -> dict | None:
    try:
        prefix, payload_b64, sig_b64 = key.strip().split(".")
        if prefix != "NS1":
            return None
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY_B64))
        payload = _b64d(payload_b64)
        pub.verify(_b64d(sig_b64), payload)
        data = json.loads(payload)
    except (ValueError, InvalidSignature, TypeError):
        return None
    exp = data.get("expires")
    if exp:
        try:
            if dt.date.fromisoformat(exp) < dt.date.today():
                data["expired"] = True
        except ValueError:
            return None
    return data


def status(settings: dict) -> dict:
    key = settings.get("license_key") or ""
    lic = verify_key(key) if key else None
    first_run = float(settings.get("first_run") or time.time())
    trial_left = max(0, TRIAL_DAYS - int((time.time() - first_run) // 86400))
    if lic and not lic.get("expired"):
        plan = "pro"
    elif trial_left > 0:
        plan = "trial"
    else:
        plan = "free"
    feats = FREE_FEATURES | (PRO_FEATURES if plan in ("pro", "trial") else set())
    return {
        "plan": plan,
        "trial_days_left": trial_left if plan == "trial" else 0,
        "name": (lic or {}).get("name"),
        "email": (lic or {}).get("email"),
        "expires": (lic or {}).get("expires"),
        "expired": bool(lic and lic.get("expired")),
        "features": sorted(feats),
    }


def has(settings: dict, feature: str) -> bool:
    return feature in status(settings)["features"]
