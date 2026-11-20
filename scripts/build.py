"""Build a self-contained NET Sniffer binary for the current platform with PyInstaller.

    python scripts/build.py                       # asset name chosen automatically
    python scripts/build.py --asset NETSniffer-Linux-x64

Old build artifacts are always deleted first: only the version being built exists on disk.
Output: dist/<asset>  (Windows .exe, macOS .zip containing NETSniffer.app, Linux single binary)
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST, BUILD = ROOT / "dist", ROOT / "build"
NAME = "NETSniffer"


def default_asset() -> str:
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    if sys.platform.startswith("win"):
        return f"{NAME}-Windows-x64.exe"
    if sys.platform == "darwin":
        return f"{NAME}-macOS-{arch}.zip"
    return f"{NAME}-Linux-{arch}"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default=default_asset())
    ap.add_argument("--skip-oui", action="store_true", help="don't refresh the vendor database")
    a = ap.parse_args()

    for d in (DIST, BUILD):
        shutil.rmtree(d, ignore_errors=True)
    if not a.skip_oui:
        run([sys.executable, "scripts/build_oui.py"])
    run([sys.executable, "scripts/make_icons.py"])

    sep = os.pathsep
    win, mac = sys.platform.startswith("win"), sys.platform == "darwin"
    icon = ROOT / "netsniffer" / "web" / ("icon.ico" if win else "icon.png")
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
        "--name", NAME, "--icon", str(icon),
        "--distpath", str(DIST), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
        "--add-data", f"{ROOT / 'netsniffer' / 'web'}{sep}netsniffer/web",
        "--add-data", f"{ROOT / 'netsniffer' / 'data'}{sep}netsniffer/data",
        "--collect-submodules", "uvicorn", "--collect-submodules", "netsniffer",
        "--collect-submodules", "zeroconf", "--collect-submodules", "websockets",
        "--collect-all", "desktop_notifier", "--collect-all", "fritzconnection",
        "--hidden-import", "segno", "--hidden-import", "defusedxml.ElementTree",
        "--exclude-module", "tkinter", "--exclude-module", "matplotlib", "--exclude-module", "numpy",
        "--exclude-module", "PIL", "--exclude-module", "pytest",
    ]
    if mac:
        cmd += ["--windowed", "--onedir", "--osx-bundle-identifier", "app.netsniffer.desktop"]
    elif win:
        cmd += ["--windowed", "--onefile"]
    else:
        cmd += ["--onefile"]
    cmd.append(str(ROOT / "packaging" / "launcher.py"))
    run(cmd)

    target = DIST / a.asset
    if mac:
        app = DIST / f"{NAME}.app"
        run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(target)])
        shutil.rmtree(app, ignore_errors=True)
        shutil.rmtree(DIST / NAME, ignore_errors=True)
    else:
        built = DIST / (f"{NAME}.exe" if win else NAME)
        built.replace(target)
        if not win:
            target.chmod(0o755)
    shutil.rmtree(BUILD, ignore_errors=True)
    print(f"\nBuilt {target.relative_to(ROOT)} ({target.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
