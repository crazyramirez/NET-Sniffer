"""Session authentication: desktop launch token, remote password (scrypt), login rate limiting."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

COOKIE = "ns_session"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str | None) -> bool:
    try:
        algo, salt_b64, dk_b64 = (stored or "").split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except (ValueError, TypeError):
        return False


class RateLimiter:
    def __init__(self, attempts: int = 6, window: float = 300) -> None:
        self.attempts, self.window = attempts, window
        self.fails: dict[str, list[float]] = {}

    def blocked(self, ip: str) -> bool:
        now = time.time()
        self.fails[ip] = [t for t in self.fails.get(ip, []) if now - t < self.window]
        return len(self.fails[ip]) >= self.attempts

    def fail(self, ip: str) -> None:
        self.fails.setdefault(ip, []).append(time.time())

    def reset(self, ip: str) -> None:
        self.fails.pop(ip, None)


def new_token() -> str:
    return secrets.token_urlsafe(32)
