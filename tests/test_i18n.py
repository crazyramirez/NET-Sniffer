"""Every locale must have the same keys/placeholders as en.json, and every key used by the code must exist."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "netsniffer"
LOC = ROOT / "web" / "locales"
LANGS = ["es", "en", "fr", "de", "it", "zh", "ja"]


def flat(d, p=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(flat(v, p + k + "."))
        else:
            out[p + k] = v
    return out


EN = flat(json.loads((LOC / "en.json").read_text(encoding="utf-8")))


def resolves(key: str) -> bool:
    return key in EN or f"{key}_one" in EN or f"{key}_other" in EN


def test_locales_complete():
    for lang in LANGS:
        data = flat(json.loads((LOC / f"{lang}.json").read_text(encoding="utf-8")))
        assert set(data) == set(EN), f"{lang}: key mismatch {set(data) ^ set(EN)}"
        for k, v in EN.items():
            assert set(re.findall(r"\{\w+\}", v)) == set(re.findall(r"\{\w+\}", data[k])), f"{lang}:{k} placeholders"


def test_static_keys_exist():
    missing = set()
    for js in (ROOT / "web" / "assets" / "js").rglob("*.js"):
        for key in re.findall(r'\bt\("([a-z0-9_.]+)"', js.read_text(encoding="utf-8")):
            if not resolves(key):
                missing.add(key)
    assert not missing, missing


def test_dynamic_families():
    from netsniffer.audit import FINDING_BY_PORT
    families = {
        "types": ["router", "mesh", "phone", "tablet", "laptop", "desktop", "server", "tv", "streamer", "speaker",
                  "camera", "printer", "console", "iot", "light", "plug", "hub", "nas", "watch", "car", "raspberry",
                  "voip", "unknown"],
        "severity": ["critical", "high", "medium", "low", "info"],
        "risk": ["none", "low", "medium", "high", "critical"],
        "monitor.status": ["online", "offline", "degraded", "unknown"],
        "nav": ["dashboard", "devices", "monitor", "speed", "security", "parental", "alerts", "settings",
                "g_overview", "g_network", "g_protection", "g_system"],
        "cams": [f"reason_{r}" for r in ("classified", "onvif", "mdns_rtsp", "rtsp", "dvr", "banner")] + ["conf_high", "conf_medium"],
        "speed": ["connect", "ping", "download", "upload"],
        "security": ["phase_network", "phase_ports"],
    }
    missing = [f"{p}.{k}" for p, ks in families.items() for k in ks if not resolves(f"{p}.{k}")]
    ids = ["wifi_open", "wifi_wep", "wifi_wpa", "wifi_wpa2", "wifi_tkip", "upnp_enabled", "router_http",
           "untrusted_devices", "cameras_present"] + [f"port_{k}" for k in set(FINDING_BY_PORT.values())]
    missing += [f"audit.f.{i}.title" for i in ids if not resolves(f"audit.f.{i}.title")]
    kinds = ["device_new", "device_online", "device_offline", "internet_down", "internet_up", "gateway_down",
             "security_issues", "camera_detected", "test"]
    missing += [f"notify.{k}.title" for k in kinds if not resolves(f"notify.{k}.title")]
    assert not missing, missing


def test_error_keys():
    src = "\n".join(p.read_text(encoding="utf-8") for p in ROOT.rglob("*.py"))
    keys = set(re.findall(r'err\(\d+, "([a-z_]+)"', src)) | set(re.findall(r'BlockError\("([a-z_]+)', src))
    missing = [k for k in keys if not resolves(f"errors.{k}")]
    assert not missing, missing
