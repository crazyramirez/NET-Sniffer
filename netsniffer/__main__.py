"""Entry point: desktop window (default) or headless server for Raspberry Pi / home servers."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import socket
import sys
import threading
import time
import webbrowser

from . import __app_name__, __version__
from .config import FROZEN, IS_WINDOWS, PACKAGE_DIR, data_dir

INSTANCE_PORT = 47391


def setup_logging(debug: bool) -> None:
    handler = logging.handlers.RotatingFileHandler(data_dir() / "netsniffer.log", maxBytes=1_000_000,
                                                   backupCount=1, encoding="utf-8")
    handlers: list[logging.Handler] = [handler]
    if sys.stderr is not None and (not FROZEN or debug):
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "asyncssh", "zeroconf", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def single_instance(wait: float) -> socket.socket | None:
    deadline = time.time() + wait
    while True:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if IS_WINDOWS:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            s.bind(("127.0.0.1", INSTANCE_PORT))
            s.listen(1)
            return s
        except OSError:
            s.close()
            if time.time() > deadline:
                return None
            time.sleep(0.5)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def icon_path() -> str | None:
    for name in ("icon.ico" if IS_WINDOWS else "icon.png",):
        p = PACKAGE_DIR / "web" / name
        if p.exists():
            return str(p)
    return None


def run_desktop(args: argparse.Namespace) -> int:
    import uvicorn

    from .app import Context, create_app

    lock = single_instance(20 if args.updated else 0)
    if lock is None:
        logging.info("another instance is already running")
        return 0
    ctx = Context(headless=False)
    app = create_app(ctx)
    port = args.port or free_port()
    ctx.port = port
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False,
                                           ws="websockets-sansio"))
    thread = threading.Thread(target=server.run, name="server", daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}/launch?token={ctx.launch_token}"
    windows: list = []

    def shutdown() -> None:
        for w in windows:
            try:
                w.destroy()
            except Exception:  # noqa: BLE001
                pass
        server.should_exit = True

    ctx.updater.shutdown = shutdown
    try:
        import webview

        theme = ctx.db.get_setting("theme", "system")
        bg = "#F5F7FB" if theme == "light" else "#0A0F1C"
        windows.append(webview.create_window(__app_name__, url, width=1380, height=900, min_size=(1024, 680),
                                             background_color=bg, text_select=True))
        webview.start(private_mode=False, storage_path=str(data_dir() / "webview"), debug=args.debug,
                      icon=icon_path())
    except Exception as exc:  # noqa: BLE001 - no GUI toolkit available → use the default browser
        logging.warning("native window unavailable (%s); opening browser", exc)
        webbrowser.open(url)
        try:
            while thread.is_alive():
                thread.join(1)
        except KeyboardInterrupt:
            pass
    finally:
        ctx.updater.install_on_exit()
        server.should_exit = True
        thread.join(8)
        lock.close()
    return 0


def run_headless(args: argparse.Namespace) -> int:
    import uvicorn

    from .app import Context, create_app

    ctx = Context(headless=True)
    app = create_app(ctx)
    ctx.port = args.port or 8765
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=ctx.port, log_config=None, access_log=False,
                                           ws="websockets-sansio"))
    ctx.updater.shutdown = lambda: setattr(server, "should_exit", True)
    from .net.interfaces import primary_ip
    ip = primary_ip() or "127.0.0.1"
    lines = [f"\n  {__app_name__} {__version__} — headless mode",
             f"  Open  http://{ip}:{ctx.port}  from any browser on your network (PC, phone, tablet)."]
    if not ctx.db.get_setting("remote_password"):
        lines.append(f"  First-time setup code: {ctx.setup_token}\n")
    if sys.stdout is not None:
        print("\n".join(lines), flush=True)
    logging.info("headless on port %s; setup code %s", ctx.port, ctx.setup_token)
    server.run()
    ctx.updater.install_on_exit()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="netsniffer", description=f"{__app_name__} — local network monitor")
    p.add_argument("--headless", action="store_true", help="run as a web server (Raspberry Pi / home server)")
    p.add_argument("--host", default="0.0.0.0", help="bind address in headless mode")
    p.add_argument("--port", type=int, default=0, help="port (headless default 8765)")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--updated", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args()
    setup_logging(args.debug)
    if os.environ.get("NETSNIFFER_HEADLESS") == "1":
        args.headless = True
    return run_headless(args) if args.headless else run_desktop(args)


if __name__ == "__main__":
    sys.exit(main())
