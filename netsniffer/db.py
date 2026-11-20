"""SQLite persistence (devices, events, speed tests, monitor samples, settings, rules)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .config import DEFAULT_SETTINGS, SECRET_SETTINGS, data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    mac TEXT, ip TEXT, hostname TEXT, name TEXT, vendor TEXT, model TEXT,
    type TEXT, os TEXT, first_seen REAL, last_seen REAL, online INTEGER DEFAULT 0,
    trusted INTEGER DEFAULT 0, favorite INTEGER DEFAULT 0, blocked INTEGER DEFAULT 0,
    is_gateway INTEGER DEFAULT 0, is_self INTEGER DEFAULT 0, randomized INTEGER DEFAULT 0,
    services TEXT DEFAULT '[]', ports TEXT DEFAULT '[]', ports_scanned REAL,
    notes TEXT DEFAULT '', type_locked INTEGER DEFAULT 0, extra TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, severity TEXT,
    device_id TEXT, params TEXT DEFAULT '{}', read INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS ix_events_dev ON events(device_id, ts);
CREATE TABLE IF NOT EXISTS speedtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, ping REAL, jitter REAL,
    download REAL, upload REAL, isp TEXT, server TEXT, ip TEXT, loss REAL
);
CREATE TABLE IF NOT EXISTS samples (
    ts REAL, latency REAL, ok INTEGER, gw_ok INTEGER, dns_ok INTEGER
);
CREATE INDEX IF NOT EXISTS ix_samples_ts ON samples(ts);
CREATE TABLE IF NOT EXISTS outages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, start REAL, end REAL, scope TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, devices TEXT DEFAULT '[]',
    schedule TEXT DEFAULT '[]', enabled INTEGER DEFAULT 1, paused_until REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, created REAL, last_used REAL, ip TEXT);
"""

DEVICE_JSON = ("services", "ports", "extra")
DEVICE_BOOL = ("online", "trusted", "favorite", "blocked", "is_gateway", "is_self", "randomized", "type_locked")


class Database:
    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "netsniffer.db")
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.executescript(SCHEMA)
        self._fernet = Fernet(self._load_key())

    # ------------------------------------------------------------------ helpers
    def _load_key(self) -> bytes:
        key_file = self.path.parent / "secret.key"
        if key_file.exists():
            return key_file.read_bytes().strip()
        key = Fernet.generate_key()
        key_file.write_bytes(key)
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
        return key

    def q(self, sql: str, args: tuple | list = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, args).fetchall()

    def x(self, sql: str, args: tuple | list = ()) -> int:
        with self._lock:
            cur = self.conn.execute(sql, args)
            return cur.lastrowid or cur.rowcount

    # ------------------------------------------------------------------ settings
    def settings(self) -> dict[str, Any]:
        out = dict(DEFAULT_SETTINGS)
        for row in self.q("SELECT key, value FROM settings"):
            try:
                val = json.loads(row["value"])
            except ValueError:
                continue
            if row["key"] in SECRET_SETTINGS and isinstance(val, str) and val:
                try:
                    val = self._fernet.decrypt(val.encode()).decode()
                except InvalidToken:
                    val = ""
            out[row["key"]] = val
        return out

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self.settings().get(key, default)

    def set_settings(self, values: dict[str, Any]) -> None:
        for key, val in values.items():
            if key in SECRET_SETTINGS and isinstance(val, str) and val:
                val = self._fernet.encrypt(val.encode()).decode()
            self.x("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(val)))

    # ------------------------------------------------------------------ devices
    @staticmethod
    def _device(row: sqlite3.Row) -> dict:
        d = dict(row)
        for k in DEVICE_JSON:
            try:
                d[k] = json.loads(d.get(k) or ("{}" if k == "extra" else "[]"))
            except ValueError:
                d[k] = {} if k == "extra" else []
        for k in DEVICE_BOOL:
            d[k] = bool(d.get(k))
        return d

    def devices(self) -> list[dict]:
        return [self._device(r) for r in self.q("SELECT * FROM devices ORDER BY online DESC, ip")]

    def device(self, device_id: str) -> dict | None:
        rows = self.q("SELECT * FROM devices WHERE id=?", (device_id,))
        return self._device(rows[0]) if rows else None

    def upsert_device(self, dev: dict) -> None:
        dev = dict(dev)
        for k in DEVICE_JSON:
            if k in dev and not isinstance(dev[k], str):
                dev[k] = json.dumps(dev[k])
        for k in DEVICE_BOOL:
            if k in dev:
                dev[k] = int(bool(dev[k]))
        cols = list(dev.keys())
        placeholders = ",".join("?" for _ in cols)
        updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "id")
        self.x(f"INSERT INTO devices({','.join(cols)}) VALUES({placeholders}) "
               f"ON CONFLICT(id) DO UPDATE SET {updates}", [dev[c] for c in cols])

    def update_device(self, device_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields = dict(fields)
        for k in DEVICE_JSON:
            if k in fields and not isinstance(fields[k], str):
                fields[k] = json.dumps(fields[k])
        for k in DEVICE_BOOL:
            if k in fields:
                fields[k] = int(bool(fields[k]))
        sets = ",".join(f"{k}=?" for k in fields)
        self.x(f"UPDATE devices SET {sets} WHERE id=?", [*fields.values(), device_id])

    def delete_device(self, device_id: str) -> None:
        self.x("DELETE FROM devices WHERE id=?", (device_id,))
        self.x("DELETE FROM events WHERE device_id=?", (device_id,))

    # ------------------------------------------------------------------ events
    def add_event(self, kind: str, severity: str = "info", device_id: str | None = None,
                  params: dict | None = None, ts: float | None = None) -> dict:
        ts = ts or time.time()
        eid = self.x("INSERT INTO events(ts, kind, severity, device_id, params) VALUES(?,?,?,?,?)",
                     (ts, kind, severity, device_id, json.dumps(params or {})))
        return {"id": eid, "ts": ts, "kind": kind, "severity": severity, "device_id": device_id,
                "params": params or {}, "read": False}

    def events(self, limit: int = 200, device_id: str | None = None, alerts_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM events"
        args: list = []
        where = []
        if device_id:
            where.append("device_id=?")
            args.append(device_id)
        if alerts_only:
            where.append("severity != 'debug'")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        out = []
        for r in self.q(sql, args):
            d = dict(r)
            d["params"] = json.loads(d["params"] or "{}")
            d["read"] = bool(d["read"])
            out.append(d)
        return out

    def unread_count(self) -> int:
        return self.q("SELECT COUNT(*) c FROM events WHERE read=0 AND severity IN ('warning','critical')")[0]["c"]

    def mark_read(self, event_id: int | None = None) -> None:
        if event_id is None:
            self.x("UPDATE events SET read=1")
        else:
            self.x("UPDATE events SET read=1 WHERE id=?", (event_id,))

    def clear_events(self) -> None:
        self.x("DELETE FROM events")

    # ------------------------------------------------------------------ speed tests
    def add_speedtest(self, r: dict) -> int:
        return self.x("INSERT INTO speedtests(ts, ping, jitter, download, upload, isp, server, ip, loss) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (r["ts"], r["ping"], r["jitter"], r["download"], r["upload"], r.get("isp"),
                       r.get("server"), r.get("ip"), r.get("loss", 0)))

    def speedtests(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM speedtests ORDER BY ts DESC LIMIT ?", (limit,))]

    # ------------------------------------------------------------------ monitor
    def add_sample(self, ts: float, latency: float | None, ok: bool, gw_ok: bool, dns_ok: bool) -> None:
        self.x("INSERT INTO samples VALUES(?,?,?,?,?)", (ts, latency, int(ok), int(gw_ok), int(dns_ok)))

    def samples(self, since: float) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM samples WHERE ts>=? ORDER BY ts", (since,))]

    def prune(self, keep_days: int = 30) -> None:
        cutoff = time.time() - keep_days * 86400
        self.x("DELETE FROM samples WHERE ts<?", (cutoff,))
        self.x("DELETE FROM events WHERE ts<? AND kind IN ('device_online','device_offline')", (cutoff,))

    def open_outage(self, start: float, scope: str) -> int:
        return self.x("INSERT INTO outages(start, end, scope) VALUES(?, NULL, ?)", (start, scope))

    def close_outage(self, oid: int, end: float) -> None:
        self.x("UPDATE outages SET end=? WHERE id=?", (end, oid))

    def outages(self, since: float) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM outages WHERE start>=? OR end IS NULL ORDER BY start DESC",
                                        (since,))]

    # ------------------------------------------------------------------ parental rules
    def rules(self) -> list[dict]:
        out = []
        for r in self.q("SELECT * FROM rules ORDER BY id"):
            d = dict(r)
            d["devices"] = json.loads(d["devices"] or "[]")
            d["schedule"] = json.loads(d["schedule"] or "[]")
            d["enabled"] = bool(d["enabled"])
            out.append(d)
        return out

    def save_rule(self, rule: dict) -> int:
        vals = (rule.get("name", ""), json.dumps(rule.get("devices", [])), json.dumps(rule.get("schedule", [])),
                int(bool(rule.get("enabled", True))), float(rule.get("paused_until") or 0))
        if rule.get("id"):
            self.x("UPDATE rules SET name=?, devices=?, schedule=?, enabled=?, paused_until=? WHERE id=?",
                   (*vals, rule["id"]))
            return int(rule["id"])
        return self.x("INSERT INTO rules(name, devices, schedule, enabled, paused_until) VALUES(?,?,?,?,?)", vals)

    def delete_rule(self, rule_id: int) -> None:
        self.x("DELETE FROM rules WHERE id=?", (rule_id,))

    # ------------------------------------------------------------------ sessions
    def add_session(self, token: str, ip: str) -> None:
        now = time.time()
        self.x("INSERT OR REPLACE INTO sessions VALUES(?,?,?,?)", (token, now, now, ip))

    def session_valid(self, token: str, max_age: float = 30 * 86400) -> bool:
        rows = self.q("SELECT last_used FROM sessions WHERE token=?", (token,))
        if not rows or time.time() - rows[0]["last_used"] > max_age:
            return False
        self.x("UPDATE sessions SET last_used=? WHERE token=?", (time.time(), token))
        return True

    def delete_session(self, token: str | None = None) -> None:
        if token is None:
            self.x("DELETE FROM sessions")
        else:
            self.x("DELETE FROM sessions WHERE token=?", (token,))
