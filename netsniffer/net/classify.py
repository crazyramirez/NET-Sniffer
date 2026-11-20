"""Heuristic device fingerprinting from vendor, names, announced services and open ports."""
from __future__ import annotations

import re

TYPES = ["router", "mesh", "phone", "tablet", "laptop", "desktop", "server", "tv", "streamer", "speaker",
         "camera", "printer", "console", "iot", "light", "plug", "hub", "nas", "watch", "car", "raspberry",
         "voip", "unknown"]

CAMERA_VENDORS = re.compile(r"hikvision|dahua|reolink|amcrest|axis comm|foscam|ezviz|wyze|arlo|eufy|ring\b|"
                            r"imou|uniview|hanwha|vivotek|annke|blink|lorex|swann|tapo|yi tech|xiaomi.*camera|"
                            r"ubiquiti.*protect|mobotix|bosch security|geovision|zmodo|wansview|sricam|vstarcam|"
                            r"shenzhen.*(vstar|reecam|jooan)", re.I)
PRINTER_VENDORS = re.compile(r"brother|epson|lexmark|kyocera|ricoh|xerox|konica|sharp corp|oki data|zebra", re.I)
PHONE_VENDORS = re.compile(r"xiaomi|oppo|vivo|oneplus|motorola|huawei|honor|realme|nothing tech|zte|nokia|"
                           r"fairphone|google|samsung|sony mobile|htc|meizu|tecno|infinix", re.I)
CONSOLE_VENDORS = re.compile(r"nintendo|sony interactive|valve", re.I)
TV_VENDORS = re.compile(r"roku|vizio|hisense|tcl|lg\b|samsung|sony|philips|panasonic|sharp|skyworth|"
                        r"amazon|nvidia", re.I)
SPEAKER_VENDORS = re.compile(r"sonos|bose|harman|bang & olufsen|denon|marantz|yamaha|amazon", re.I)
NAS_VENDORS = re.compile(r"synology|qnap|western digital|asustor|buffalo|terramaster|seagate", re.I)
IOT_VENDORS = re.compile(r"espressif|tuya|shelly|allterco|itead|sonoff|ecobee|nest|withings|netatmo|tado|"
                         r"broadlink|meross|wiz|lifx|nanoleaf|yeelight|aqara|lumi united|switchbot|"
                         r"texas instruments|silicon labs|nordic|particle|chongqing fugui|hui zhou gaoshengda|"
                         r"azurewave.*iot|realtek.*iot|beken|bouffalo", re.I)
LIGHT_VENDORS = re.compile(r"philips hue|signify|lifx|nanoleaf|yeelight|wiz connected", re.I)
NET_VENDORS = re.compile(r"tp-link|netgear|ubiquiti|asus|d-link|linksys|mikrotik|avm|zyxel|sagemcom|"
                         r"askey|mitrastar|arcadyan|huawei|zte|technicolor|sercomm|cisco|aruba|ruckus|"
                         r"eero|plume|tenda|mercusys|cudy|gl technologies|openwrt|draytek", re.I)
PC_NIC_VENDORS = re.compile(r"intel|realtek|liteon|lite-on|azurewave|rivet|killer|qualcomm atheros|"
                            r"mediatek|dell|lenovo|hp\b|hewlett|asus|msi|micro-star|gigabyte|acer|"
                            r"microsoft|framework|clevo|tongfang|foxconn|hon hai|wistron|quanta|pegatron", re.I)

HOST_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"iphone|android|galaxy|pixel|redmi|oneplus|xperia|moto\s?g|huawei-|honor-|poco|oppo|vivo", re.I), "phone"),
    (re.compile(r"ipad|tab[\s-]|tablet|kindle|fire-?hd", re.I), "tablet"),
    (re.compile(r"watch", re.I), "watch"),
    (re.compile(r"macbook|laptop|notebook|thinkpad|xps|surface|zenbook|vivobook|ideapad|legion|yoga|"
                r"chromebook|elitebook|latitude|inspiron|pavilion|spectre|envy|omen", re.I), "laptop"),
    (re.compile(r"imac|mac-?mini|mac-?pro|mac-?studio|desktop|-pc\b|^pc-|workstation|tower", re.I), "desktop"),
    (re.compile(r"raspberry|raspberrypi|\brpi|pihole|pi-hole|octopi", re.I), "raspberry"),
    (re.compile(r"chromecast|google-?tv|android-?tv|appletv|apple-tv|roku|fire-?tv|firestick|shield|"
                r"bravia|\btv\b|smart-?tv|webos|tizen", re.I), "tv"),
    (re.compile(r"echo|alexa|homepod|sonos|nest-?(mini|audio|hub)|google-?home|speaker", re.I), "speaker"),
    (re.compile(r"\bcam\b|ipcam|camera|webcam|\bipc\b|\bnvr\b|\bdvr\b|doorbell", re.I), "camera"),
    (re.compile(r"printer|print|laserjet|officejet|deskjet|envy-?photo|mfc-|hl-|ecotank|pixma", re.I), "printer"),
    (re.compile(r"playstation|ps[45]|xbox|nintendo|switch|steamdeck|steam-deck", re.I), "console"),
    (re.compile(r"nas|synology|diskstation|qnap|truenas|unraid", re.I), "nas"),
    (re.compile(r"esp[-_]?\w*|tasmota|shelly|sonoff|tuya|smartplug|plug", re.I), "iot"),
    (re.compile(r"bulb|light|lamp|hue", re.I), "light"),
    (re.compile(r"server|srv|proxmox|esxi|ubuntu|debian|homeassistant|hassio", re.I), "server"),
    (re.compile(r"tesla|car", re.I), "car"),
]

SERVICE_HINTS: list[tuple[str, str]] = [
    ("_googlecast", "tv"), ("_androidtvremote2", "tv"), ("_amzn-wplay", "tv"), ("_nvstream", "desktop"),
    ("_ipp", "printer"), ("_ipps", "printer"), ("_printer", "printer"), ("_pdl-datastream", "printer"),
    ("_uscan", "printer"), ("_scanner", "printer"), ("_sonos", "speaker"), ("_spotify-connect", "speaker"),
    ("_hue", "hub"), ("_esphomelib", "iot"), ("_shelly", "plug"), ("_hap", "iot"), ("_matter", "iot"),
    ("_home-assistant", "server"), ("_octoprint", "server"), ("_plexmediasvr", "server"),
    ("_rtsp", "camera"), ("_adisk", "nas"), ("_nanoleafapi", "light"), ("_elg", "light"), ("_miio", "iot"),
    ("_apple-mobdev2", "phone"), ("_workstation", "desktop"), ("_rfb", "desktop"),
]

APPLE_MODELS: list[tuple[str, str]] = [
    ("iphone", "phone"), ("ipad", "tablet"), ("watch", "watch"), ("appletv", "tv"),
    ("audioaccessory", "speaker"), ("macbook", "laptop"), ("imac", "desktop"), ("macmini", "desktop"),
    ("macpro", "desktop"), ("mac", "laptop"),
]


def classify(dev: dict, gateway_vendor_prefix: str | None = None) -> tuple[str, str | None]:
    """Return (type, os_guess)."""
    vendor = (dev.get("vendor") or "")
    host = " ".join(filter(None, [dev.get("hostname"), dev.get("mdns_name"), dev.get("netbios"),
                                  dev.get("ssdp_name")]))
    model = (dev.get("model") or "")
    services = " ".join(dev.get("services") or [])
    ports = {p["port"] if isinstance(p, dict) else p for p in (dev.get("ports") or [])} | set(dev.get("open_hint") or [])
    ssdp_type = dev.get("ssdp_type") or ""
    wsd = dev.get("wsd") or {}
    os_guess = None

    if dev.get("is_gateway"):
        return "router", "Router OS"
    if gateway_vendor_prefix and dev.get("mac", "")[:8] == gateway_vendor_prefix:
        return "mesh", None

    # Apple model identifiers announced via mDNS are very reliable
    if re.match(r"(iPhone|iPad|Watch|AppleTV|AudioAccessory|MacBook|iMac|Macmini|MacPro|Mac)\d", model):
        low = model.lower()
        for key, t in APPLE_MODELS:
            if low.startswith(key):
                os_guess = {"phone": "iOS", "tablet": "iPadOS", "watch": "watchOS", "tv": "tvOS",
                            "speaker": "audioOS"}.get(t, "macOS")
                return t, os_guess

    if wsd.get("camera") or CAMERA_VENDORS.search(vendor) or "camera" in model.lower():
        return "camera", "Embedded Linux"
    if (ports & {554, 8554, 37777, 34567}) and not (ports & {445, 3389, 62078}):
        if not re.search(r"apple|sonos|google|amazon", vendor, re.I):
            return "camera", "Embedded Linux"
    if wsd.get("printer") or PRINTER_VENDORS.search(vendor) or (ports & {9100, 515, 631} and "_ipp" in services):
        return "printer", None
    if "MediaRenderer" in ssdp_type and TV_VENDORS.search(vendor):
        return "tv", None

    if "raspberry" in vendor.lower():
        return "raspberry", "Linux"
    for svc, t in SERVICE_HINTS:
        if svc in services:
            if t == "phone":
                os_guess = "iOS" if "apple" in vendor.lower() or dev.get("randomized") else None
            if svc == "_workstation" and ports & {22}:
                return "server", "Linux"
            return t, os_guess

    for rx, t in HOST_HINTS:
        if host and rx.search(host):
            if t == "phone":
                os_guess = "iOS" if re.search(r"iphone", host, re.I) else "Android"
            elif t == "tablet":
                os_guess = "iPadOS" if re.search(r"ipad", host, re.I) else "Android"
            elif t in ("laptop", "desktop"):
                os_guess = "macOS" if re.search(r"mac", host, re.I) else ("Windows" if ports & {135, 139, 445, 3389}
                                                                          else None)
            return t, os_guess

    if wsd.get("computer"):
        return "desktop", "Windows"
    if 62078 in ports:
        return "phone", "iOS"
    if "raspberry" in vendor.lower():
        return "raspberry", "Linux"
    if NAS_VENDORS.search(vendor):
        return "nas", "Linux"
    if CONSOLE_VENDORS.search(vendor):
        return "console", None
    if LIGHT_VENDORS.search(vendor):
        return "light", None
    if SPEAKER_VENDORS.search(vendor) and "amazon" not in vendor.lower():
        return "speaker", None
    if IOT_VENDORS.search(vendor):
        return "iot", "RTOS"
    if ports & {3389, 135} or ports & {445, 139}:
        return "desktop", "Windows"
    if NET_VENDORS.search(vendor) and ports & {80, 443} and not ports & {62078, 445}:
        return "mesh", None
    if re.search(r"apple", vendor, re.I):
        return ("laptop", "macOS") if ports & {22, 445, 548, 5900} else ("phone", "iOS")
    if PHONE_VENDORS.search(vendor):
        return "phone", "Android"
    if dev.get("randomized"):
        return "phone", None
    if PC_NIC_VENDORS.search(vendor):
        return ("laptop" if re.search(r"intel|azurewave|liteon|lite-on|rivet|killer|mediatek", vendor, re.I)
                else "desktop"), None
    if ports & {22} and ports & {80, 443}:
        return "server", "Linux"
    if TV_VENDORS.search(vendor):
        return "tv", None
    return "unknown", None


def display_name(dev: dict) -> str:
    for key in ("name", "mdns_name", "netbios", "hostname", "ssdp_name"):
        v = dev.get(key)
        if v and not re.fullmatch(r"[\d.]+", v):
            return v
    if dev.get("model"):
        return f"{dev.get('vendor') + ' ' if dev.get('vendor') and dev['vendor'] not in dev['model'] else ''}{dev['model']}"
    if dev.get("vendor"):
        return dev["vendor"]
    return dev.get("ip") or "?"
