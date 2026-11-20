<p align="center"><img src="docs/assets/readme-header.png" alt="NET Sniffer — See every device. Secure your network." width="100%"></p>

<p align="center">
  <a href="https://github.com/crazyramirez/NET-Sniffer/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/crazyramirez/NET-Sniffer?style=flat-square&color=6366F1"></a>
  <img alt="Platforms" src="https://img.shields.io/badge/Windows%20·%20macOS%20·%20Linux%20·%20Raspberry%20Pi-0EA5E9?style=flat-square">
  <img alt="Free" src="https://img.shields.io/badge/price-free-10B981?style=flat-square">
  <img alt="Languages" src="https://img.shields.io/badge/ES%20·%20EN%20·%20FR%20·%20DE%20·%20IT%20·%20中文%20·%20日本語-8B5CF6?style=flat-square">
</p>

**NET Sniffer** is a free desktop app that shows every device on your Wi-Fi/LAN, audits your network's security, tests your internet speed and alerts you when something changes — with a clean light/dark interface in 7 languages.

> Built for **networks you own or administer**. NET Sniffer only uses standard discovery protocols and connection checks: no exploitation, no password guessing, no traffic interception, no ARP spoofing.

## Download

| Platform | File |
|---|---|
| Windows 10/11 (x64) | [NETSniffer-Windows-x64.exe](https://github.com/crazyramirez/NET-Sniffer/releases/latest/download/NETSniffer-Windows-x64.exe) |
| macOS Apple Silicon | [NETSniffer-macOS-arm64.zip](https://github.com/crazyramirez/NET-Sniffer/releases/latest/download/NETSniffer-macOS-arm64.zip) |
| macOS Intel | [NETSniffer-macOS-x64.zip](https://github.com/crazyramirez/NET-Sniffer/releases/latest/download/NETSniffer-macOS-x64.zip) |
| Linux x64 | [NETSniffer-Linux-x64](https://github.com/crazyramirez/NET-Sniffer/releases/latest/download/NETSniffer-Linux-x64) |
| Linux ARM64 / Raspberry Pi | [NETSniffer-Linux-arm64](https://github.com/crazyramirez/NET-Sniffer/releases/latest/download/NETSniffer-Linux-arm64) |

The app updates itself from GitHub Releases. Only the latest version is ever published.

<details><summary>First launch notes</summary>

- **Windows**: SmartScreen may warn about an unsigned app → *More info* → *Run anyway*.
- **macOS**: unzip, move `NETSniffer.app` to Applications, then right-click → *Open* the first time (unsigned build).
- **Linux**: `chmod +x NETSniffer-Linux-x64 && ./NETSniffer-Linux-x64`. A native window needs GTK + WebKit2GTK (`gir1.2-webkit2-4.1`); otherwise the UI opens in your browser.
</details>

## Features

- **Device discovery** — IP, MAC, vendor (IEEE registry), model, hostname, OS guess and device type for everything connected. Uses ARP resolution, mDNS/Bonjour, NetBIOS, SSDP/UPnP and WS-Discovery. No admin rights needed.
- **Connection history** — first/last seen, online/offline timeline, IP changes, private (randomized) MAC detection.
- **Intruder detection** — mark known devices as trusted; new devices trigger instant alerts (90-second watcher).
- **Security audit** — score and grade for your network: Wi-Fi encryption, UPnP exposure, router admin over HTTP, risky services (Telnet, exposed databases, Docker API, ADB, VNC, RTSP…), each with step-by-step fixes. Exportable HTML report.
- **Hidden camera finder** — ONVIF discovery, RTSP/DVR services, camera vendors and web-server fingerprints.
- **Ports & services** — quick, common (~120) or full (~1,100) TCP port inventory per device with banners and risk levels.
- **Internet monitor** — continuous latency/packet-loss tracking, outage detection with duration log, uptime %.
- **Speed test** — download, upload, ping and jitter (Cloudflare edge) with an animated gauge and history.
- **Block devices & parental controls** — pause internet per device or on schedules (bedtime, school hours…), enforced on *your* router via its official admin interface: OpenWrt/Linux routers (SSH + nftables/iptables), AVM FRITZ!Box (TR-064) or a Linux box acting as gateway.
- **Alerts** — in-app, desktop notifications, plus push to your phone via ntfy, Telegram or webhooks.
- **Remote access** — open NET Sniffer from your phone or another PC (password protected, QR code), or run it 24/7 on a Raspberry Pi.
- **Wake-on-LAN, ping, CSV export, light/dark themes, 7 languages** (auto-detected): Español, English, Français, Deutsch, Italiano, 中文, 日本語.

## Raspberry Pi / home server

Runs headless as a service and serves the full UI to any browser on your network:

```sh
curl -fsSL https://raw.githubusercontent.com/crazyramirez/NET-Sniffer/main/packaging/install-linux.sh | sudo sh
```

Open `http://<pi-ip>:8765`, enter the setup code printed by the installer and choose a password. For access away from home, use a VPN (WireGuard/Tailscale) rather than opening router ports.

## Run from source

```sh
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m netsniffer                  # desktop window
python -m netsniffer --headless       # web server on :8765
python -m pytest -q
```

## Build & release

| Task | Command |
|---|---|
| Build for the current OS | `python scripts/build.py` → `dist/` |
| Publish a new version (Windows) | `.\scripts\release.ps1` (or `-Bump minor`, `-Version 2.0.0`) |

`release.ps1` bumps the version, runs the tests, builds the Windows `.exe`, pushes the tag and publishes the GitHub release. Publishing triggers [`.github/workflows/release.yml`](.github/workflows/release.yml), which builds macOS (arm64/x64) and Linux (x64/arm64), attaches them to the same release and deletes every older release, tag and workflow run. Local builds always wipe previous artifacts first.

Brand images are generated with `python scripts/gen_brand_images.py` (needs `OPENAI_API_KEY` in `.env`).

## Architecture

```
netsniffer/
  __main__.py        desktop (pywebview) / headless launcher
  app.py             FastAPI REST + WebSocket API, auth, remote listener
  engine.py          discovery orchestration, history merge, intruder alerts
  net/               arp · names (mDNS/SSDP/NetBIOS/WSD) · oui · classify · ports · interfaces
  audit.py           security audit & camera finder
  monitor.py         internet/outage monitor, live throughput
  speedtest.py       Cloudflare speed test
  blocking/          router backends + parental schedules
  updater.py         GitHub Releases self-update
  web/               UI (vanilla ES modules, no build step) + locales
```

## Privacy

Everything stays on your machine. External requests: Cloudflare (speed test and optional public-IP/ISP lookup), GitHub (update checks) and the push services you configure. Router credentials are stored encrypted locally.
