import datetime as dt
import struct

import pytest

from netsniffer.auth import hash_password, verify_password
from netsniffer.blocking import _script, rule_active
from netsniffer.net import oui
from netsniffer.net.classify import classify, display_name
from netsniffer.net.names import _nbstat_packet, _parse_nbstat
from netsniffer.net.utils import NotLocalError, is_local_ip, is_randomized_mac, norm_mac, require_local
from netsniffer.updater import parse_version


def test_local_ip_guard():
    assert is_local_ip("192.168.1.10") and is_local_ip("10.0.0.5") and is_local_ip("172.16.4.4")
    for ip in ("8.8.8.8", "100.64.1.1", "224.0.0.251", "0.0.0.0", "not-an-ip", "::1"):
        assert not is_local_ip(ip)
    with pytest.raises(NotLocalError):
        require_local("1.1.1.1")


def test_mac_helpers():
    assert norm_mac("AA-BB-CC-01-02-03") == "aa:bb:cc:01:02:03"
    assert norm_mac("ff:ff:ff:ff:ff:ff") is None and norm_mac("01:00:5e:00:00:fb") is None
    assert is_randomized_mac("9a:90:e9:12:08:1a") and not is_randomized_mac("d8:3a:dd:48:b8:2f")


def test_oui_lookup():
    assert oui.lookup("b8:27:eb:00:00:01") == "Raspberry Pi"
    assert oui.lookup(None) is None


def test_classify():
    assert classify({"is_gateway": True})[0] == "router"
    assert classify({"model": "iPhone14,2", "vendor": ""}) == ("phone", "iOS")
    assert classify({"vendor": "Hikvision", "mac": "aa"})[0] == "camera"
    assert classify({"vendor": "Raspberry Pi", "services": ["_workstation._tcp"], "mac": "x"})[0] == "raspberry"
    assert classify({"vendor": "TP-Link", "mac": "8c:86:dd:00:00:01"}, "8c:86:dd")[0] == "mesh"
    assert classify({"vendor": "", "randomized": True, "mac": "9a:00"})[0] == "phone"
    assert display_name({"name": "", "mdns_name": "Living Room", "ip": "1"}) == "Living Room"


def test_rule_schedule_overnight():
    rule = {"enabled": True, "schedule": [{"days": [0], "start": "22:00", "end": "07:00"}]}
    mon_23 = dt.datetime(2024, 1, 1, 23, 0)   # Monday
    tue_06 = dt.datetime(2024, 1, 2, 6, 30)   # Tuesday morning, continues Monday's slot
    tue_23 = dt.datetime(2024, 1, 2, 23, 0)
    assert rule_active(rule, mon_23) and rule_active(rule, tue_06) and not rule_active(rule, tue_23)
    assert not rule_active({**rule, "enabled": False}, mon_23)


def test_block_script_rejects_injection():
    script = _script(["aa:bb:cc:dd:ee:ff", "aa:bb:cc:dd:ee:ff; rm -rf /"], "nft")
    assert "rm -rf" not in script and "aa:bb:cc:dd:ee:ff" in script


def test_versions_and_passwords():
    assert parse_version("1.10.0") > parse_version("1.9.9") > parse_version("1.9")
    h = hash_password("correct horse")
    assert verify_password("correct horse", h) and not verify_password("nope", h)


def test_netbios_parse():
    assert len(_nbstat_packet(1)) == 50
    names = b"LEGIONPC       \x00" + struct.pack(">H", 0x0400) + b"WORKGROUP      \x00" + struct.pack(">H", 0x8400)
    pkt = b"\x00" * 56 + bytes([2]) + names + b"\x00" * 6
    assert _parse_nbstat(pkt) == ("LEGIONPC", "WORKGROUP")
