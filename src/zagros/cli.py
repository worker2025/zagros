"""Command line entry point: ``zagros [script.py [args...]]``."""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .launcher import open_window
from .server import ZagrosServer


def _say(msg: str, ascii_fallback: str | None = None) -> None:
    """Print without ever crashing: stdout is None under pythonw and may be cp437/cp1252."""
    if sys.stdout is None:
        return
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        try:
            print(ascii_fallback or msg.encode("ascii", "replace").decode("ascii"), flush=True)
        except OSError:
            pass
    except OSError:
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="zagros",
        description="Persian-first console for learning Python (RTL/bidi-correct output).")
    ap.add_argument("script", nargs="?", help="a .py file to run (default: interactive console)")
    ap.add_argument("args", nargs=argparse.REMAINDER, help="arguments passed to the script")
    ap.add_argument("--repl", action="store_true", help="start the Python REPL immediately")
    ap.add_argument("--no-shell", action="store_true", help="disable the command prompt (old behaviour)")
    ap.add_argument("--chdir-script", action="store_true",
                    help="work in the script's folder (used by the Explorer right-click entry)")
    ap.add_argument("--register", action="store_true",
                    help="Windows: add 'اجرا با zagros' to the right-click menu of .py files")
    ap.add_argument("--unregister", action="store_true", help="Windows: remove that menu entry")
    ap.add_argument("--result", action="store_true",
                    help="start in 'big result' mode: only the program's output, very large")
    ap.add_argument("--no-window-control", action="store_true",
                    help="do not move/resize/pin the window (always-on-top, size lock, ...)")
    ap.add_argument("--port", type=int, default=0, help="local port (default: random)")
    ap.add_argument("--no-browser", action="store_true", help="only print the URL")
    ap.add_argument("--version", action="version", version=f"zagros {__version__}")
    ns = ap.parse_args(argv)

    if ns.register or ns.unregister:
        if sys.platform != "win32":
            _say("این گزینه فقط در ویندوز کار می‌کند.", "This option only works on Windows.")
            return 1
        from . import integration
        done = integration.register() if ns.register else integration.unregister()
        _say(f"{len(done)} registry key(s) {'written' if ns.register else 'removed'}.")
        return 0

    srv = ZagrosServer(ns.port, shell=not ns.no_shell, window=not ns.no_window_control,
                       result_mode=ns.result)
    sh = srv.shell
    try:
        if sh:
            sh.welcome(prompt=not (ns.script or ns.repl))
        if ns.script and not ns.repl:
            if not os.path.isfile(ns.script):
                raise FileNotFoundError(ns.script)
            if ns.chdir_script and sh:
                sh.cwd = os.path.dirname(os.path.abspath(ns.script))
            srv.session.start_script(ns.script, ns.args, cwd=sh.cwd if sh else os.getcwd())
        elif ns.script is None and not ns.repl and sh:
            pass                                  # idle shell prompt
        else:
            srv.session.start_repl()
    except FileNotFoundError:
        _say(f"فایل پیدا نشد: {ns.script}", f"file not found: {ns.script}")
        return 2
    _say(f"zagros {__version__} - {srv.url}")
    if not ns.no_browser:
        saved = srv.settings.get()["window"]
        size = (saved["w"], saved["h"]) if saved["w"] and saved["h"] else None
        if open_window(srv.url, size=size) and srv.window:
            srv.window.attach_async(saved)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        srv.server_close()
    return 0
