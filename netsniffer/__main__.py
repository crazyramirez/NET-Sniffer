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

def setup_logging(debug: bool, console: bool = False) -> None:
    handler = logging.handlers.RotatingFileHandler(data_dir() / "netsniffer.log", maxBytes=1_000_000,
                                                   backupCount=1, encoding="utf-8")
    handlers: list[logging.Handler] = [handler]
    if sys.stderr is not None and (not FROZEN or debug or console):
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "asyncssh", "zeroconf", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


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

    from . import desktop, i18n
    from .app import Context, create_app
    from .config import IS_MAC

    lock = desktop.acquire_instance(20 if args.updated else 0)
    if lock is None:
        logging.info("another instance is running; asked it to show its window")
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
    state: dict = {"window": None, "quitting": False, "hinted": False}

    def show() -> None:
        w = state["window"]
        if w is None:
            webbrowser.open(url)
            return
        for fn in (w.show, w.restore):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

    def quit_app() -> None:
        state["quitting"] = True
        tray.stop()
        w = state["window"]
        if w is not None:
            try:
                w.destroy()
                return
            except Exception:  # noqa: BLE001
                pass
        server.should_exit = True

    def toggle_notifications() -> None:
        enabled = not ctx.db.get_setting("notify_enabled", True)
        ctx.db.set_settings({"notify_enabled": enabled})
        ctx.run(ctx.hub.broadcast("settings", {"settings": ctx.public_settings(), "remote": ctx.remote_status()}))
        tray.refresh()

    tray = desktop.Tray(lambda: i18n.resolve(ctx.db.get_setting("language")), show,
                        lambda: ctx.run(ctx.engine.scan(full=True)), toggle_notifications,
                        lambda: bool(ctx.db.get_setting("notify_enabled", True)), quit_app)
    desktop.serve_instance(lock, show)
    ctx.notifier.on_click = show
    ctx.updater.shutdown = quit_app
    ctx.tray = tray
    try:
        import webview

        tray.start()
        theme = ctx.db.get_setting("theme", "system")
        bg = "#F5F7FB" if theme == "light" else "#0A0F1C"
        w = webview.create_window(__app_name__, url, width=1380, height=900, min_size=(1024, 680),
                                  background_color=bg, text_select=True,
                                  hidden=bool(args.background and tray.available))
        state["window"] = w

        def on_closing():
            if state["quitting"]:
                return True
            if tray.available and ctx.db.get_setting("background", True):
                threading.Timer(0.05, w.hide).start()
                if not state["hinted"]:
                    state["hinted"] = True
                    ctx.run(ctx.notifier.hint_background())
                return False
            return True

        w.events.closing += on_closing
        webview.start(private_mode=False, storage_path=str(data_dir() / "webview"), debug=args.debug,
                      icon=icon_path())
    except Exception as exc:  # noqa: BLE001 - no GUI toolkit available → use the default browser
        logging.warning("native window unavailable (%s); opening browser", exc)
        state["window"] = None
        if not tray.available and not IS_MAC:
            tray.start()
        webbrowser.open(url)
        try:
            while thread.is_alive() and not state["quitting"]:
                thread.join(1)
        except KeyboardInterrupt:
            pass
    finally:
        tray.stop()
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
    p.add_argument("--background", action="store_true", help="start hidden in the system tray")
    p.add_argument("--updated", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args()
    if os.environ.get("NETSNIFFER_HEADLESS") == "1":
        args.headless = True
    setup_logging(args.debug, console=args.headless)
    return run_headless(args) if args.headless else run_desktop(args)


if __name__ == "__main__":
    sys.exit(main())
