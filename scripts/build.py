"""Build installable NET Sniffer packages for the current platform.

    python scripts/build.py

Windows → dist/NETSniffer-Setup-Windows-x64.exe   (Inno Setup, per-user, no admin)
macOS   → dist/NETSniffer-macOS-<arch>.dmg        (drag to Applications)
Linux   → dist/NETSniffer-Linux-<arch>.deb        (menu entry + icon, /opt/netsniffer)
          dist/NETSniffer-Linux-<arch>            (single binary: Raspberry Pi service & self-update)

Old artifacts are always deleted first: only the version being built exists on disk.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST, BUILD = ROOT / "dist", ROOT / "build"
PYI = BUILD / "pyi"
NAME = "NETSniffer"
WIN, MAC = sys.platform.startswith("win"), sys.platform == "darwin"
ARCH = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"


def version() -> str:
    src = (ROOT / "netsniffer" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', src).group(1)


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, cwd=ROOT, **kw)


def pyinstaller(onefile: bool) -> None:
    sep = os.pathsep
    icon = ROOT / "netsniffer" / "web" / ("icon.ico" if WIN else "icon.png")
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
        "--name", NAME, "--icon", icon,
        "--distpath", PYI, "--workpath", BUILD / "work", "--specpath", BUILD,
        "--add-data", f"{ROOT / 'netsniffer' / 'web'}{sep}netsniffer/web",
        "--add-data", f"{ROOT / 'netsniffer' / 'data'}{sep}netsniffer/data",
        "--collect-submodules", "uvicorn", "--collect-submodules", "netsniffer",
        "--collect-submodules", "zeroconf", "--collect-submodules", "websockets",
        "--collect-submodules", "pystray",
        "--collect-all", "desktop_notifier", "--collect-all", "fritzconnection",
        "--hidden-import", "segno", "--hidden-import", "defusedxml.ElementTree",
        "--exclude-module", "tkinter", "--exclude-module", "matplotlib", "--exclude-module", "numpy",
        "--exclude-module", "pytest",
        "--onefile" if onefile else "--onedir",
    ]
    if WIN or MAC:
        cmd.append("--windowed")
    if MAC:
        cmd += ["--osx-bundle-identifier", "app.netsniffer.desktop"]
    cmd.append(ROOT / "packaging" / "launcher.py")
    run(cmd)


def iscc() -> Path:
    for p in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
              Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
              Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe"):
        if p.exists():
            return p
    found = shutil.which("iscc") or shutil.which("ISCC")
    if not found:
        sys.exit("Inno Setup 6 not found (winget install JRSoftware.InnoSetup)")
    return Path(found)


def build_windows(ver: str) -> list[Path]:
    pyinstaller(onefile=False)
    env = dict(os.environ, NS_VERSION=ver, NS_SOURCE=str(PYI / NAME), NS_OUTDIR=str(DIST),
               NS_ICON=str(ROOT / "netsniffer" / "web" / "icon.ico"))
    run([iscc(), "/Q", ROOT / "packaging" / "windows" / "installer.iss"], env=env)
    return [DIST / f"{NAME}-Setup-Windows-x64.exe"]


def build_macos(ver: str) -> list[Path]:
    pyinstaller(onefile=False)
    stage = BUILD / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    run(["ditto", PYI / f"{NAME}.app", stage / f"{NAME}.app"])
    (stage / "Applications").symlink_to("/Applications")
    out = DIST / f"{NAME}-macOS-{ARCH}.dmg"
    run(["hdiutil", "create", "-volname", "NET Sniffer", "-srcfolder", stage, "-ov", "-format", "UDZO", out])
    return [out]


def build_linux(ver: str) -> list[Path]:
    pyinstaller(onefile=True)
    raw = DIST / f"{NAME}-Linux-{ARCH}"
    shutil.copy2(PYI / NAME, raw)
    raw.chmod(0o755)
    outs = [raw]
    if shutil.which("dpkg-deb"):
        pkg = BUILD / "deb"
        shutil.rmtree(pkg, ignore_errors=True)
        (pkg / "DEBIAN").mkdir(parents=True)
        (pkg / "opt" / "netsniffer").mkdir(parents=True)
        (pkg / "usr" / "bin").mkdir(parents=True)
        (pkg / "usr" / "share" / "applications").mkdir(parents=True)
        icons = pkg / "usr" / "share" / "icons" / "hicolor" / "512x512" / "apps"
        icons.mkdir(parents=True)
        shutil.copy2(raw, pkg / "opt" / "netsniffer" / NAME)
        shutil.copy2(ROOT / "netsniffer" / "web" / "icon-512.png", icons / "netsniffer.png")
        (pkg / "usr" / "bin" / "netsniffer").symlink_to(f"/opt/netsniffer/{NAME}")
        (pkg / "usr" / "share" / "applications" / "netsniffer.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=NET Sniffer\nGenericName=Network monitor\n"
            "Comment=See every device. Secure your network.\nExec=/opt/netsniffer/NETSniffer\nIcon=netsniffer\n"
            "Terminal=false\nCategories=Network;Monitor;Security;\nStartupWMClass=NETSniffer\n", encoding="utf-8")
        deb_arch = "arm64" if ARCH == "arm64" else "amd64"
        (pkg / "DEBIAN" / "control").write_text(
            f"Package: netsniffer\nVersion: {ver}\nSection: net\nPriority: optional\nArchitecture: {deb_arch}\n"
            "Maintainer: NET Sniffer <noreply@users.noreply.github.com>\n"
            "Recommends: gir1.2-webkit2-4.1, gir1.2-ayatanaappindicator3-0.1\n"
            "Homepage: https://github.com/crazyramirez/NET-Sniffer\n"
            "Description: Network monitor and security auditor for your own network\n"
            " Discovers every device on your LAN, audits security, tests speed and alerts you.\n",
            encoding="utf-8")
        out = DIST / f"{NAME}-Linux-{ARCH}.deb"
        run(["dpkg-deb", "--root-owner-group", "--build", pkg, out])
        outs.append(out)
    return outs


def main() -> int:
    for d in (DIST, BUILD):
        shutil.rmtree(d, ignore_errors=True)
    DIST.mkdir()
    if "--skip-oui" not in sys.argv:
        run([sys.executable, "scripts/build_oui.py"])
    run([sys.executable, "scripts/make_icons.py"])
    ver = version()
    outs = build_windows(ver) if WIN else build_macos(ver) if MAC else build_linux(ver)
    shutil.rmtree(BUILD, ignore_errors=True)
    print()
    for o in outs:
        print(f"Built {o.relative_to(ROOT)}  ({o.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
