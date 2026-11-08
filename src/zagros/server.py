"""Tiny local HTTP server: serves the console UI and bridges it to a Session.

Security model (the server can run code, so it must not be reachable by web pages):
  * binds to 127.0.0.1 only;
  * every API/event request needs a random per-launch token;
  * the Host header must be 127.0.0.1:<port> or localhost:<port> (DNS-rebinding guard);
  * no CORS headers are ever sent and OPTIONS is not implemented.
"""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import select
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from . import text as fatext
from .dropfiles import (MAX_UPLOAD, SCRIPT_EXTS, default_roots, locate, quote_path, safe_script_name,
                        save_upload)
from .session import Session, python_exe
from .settings import Settings
from .shell import Shell
from .winctl import WindowController

WEB = Path(__file__).resolve().parent / "web"
MAX_BODY = 64 * 1024
_STATIC = {"/": "index.html", "/index.html": "index.html", "/console.js": "console.js",
           "/style.css": "style.css", "/icon.svg": "icon.svg"}

_PICK_CODE = (
    "import tkinter as tk\n"
    "from tkinter import filedialog\n"
    "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
    "print(filedialog.askopenfilename(title='انتخاب فایل پایتون', "
    "filetypes=[('Python', '*.py *.pyw'), ('All files', '*.*')]))\n"
)


class ZagrosServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int = 0, *, token: str | None = None,
                 session: Session | None = None, grace: float = 10.0,
                 auto_exit: bool = True, shell: bool = True, start_dir: str | None = None,
                 history_path=None, settings_path=None, window: bool = True, window_api="auto",
                 drop_dir=None, result_mode: bool = False):
        super().__init__(("127.0.0.1", port), Handler)
        self.token = token or secrets.token_urlsafe(24)
        self.session = session or Session()
        self.grace = grace
        self.auto_exit = auto_exit
        self.result_mode = result_mode
        self.port = self.server_address[1]
        self.settings = Settings(settings_path)
        self.window = (WindowController(f"zagros:{self.port}", window_api, self.settings)
                       if window else None)
        self.drop_dir = drop_dir or os.path.join(os.path.expanduser("~"), ".zagros", "dropped")
        self.shell = (Shell(self.session, start_dir, history_path=history_path, on_quit=self.close,
                            winctl=self.window, settings=self.settings) if shell else None)
        self.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.closing = False
        self._clients = 0
        self._had_client = False
        self._gone_at = time.monotonic()
        self._lock = threading.Lock()
        if auto_exit:
            threading.Thread(target=self._watchdog, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?t={self.token}" + ("&m=result" if self.result_mode else "")

    def client_connected(self) -> None:
        with self._lock:
            self._clients += 1
            self._had_client = True

    def client_gone(self) -> None:
        with self._lock:
            self._clients -= 1
            self._gone_at = time.monotonic()

    def _watchdog(self) -> None:
        while not self.closing:
            time.sleep(1.0)
            with self._lock:
                idle = (self._had_client and self._clients <= 0
                        and time.monotonic() - self._gone_at > self.grace)
            if idle:
                self.close()
                return

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        if self.shell:
            self.shell.close()
        if self.window:
            self.window.stop()
        self.session.stop()
        threading.Thread(target=self.shutdown, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server_version = "zagros"
    sys_version = ""

    def log_message(self, *args) -> None:  # keep the learner's console quiet
        pass

    # -- helpers -----------------------------------------------------------
    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self.server.allowed_hosts

    def _token_ok(self, qs) -> bool:
        tok = self.headers.get("X-FC-Token") or (qs.get("t") or [""])[0]
        return secrets.compare_digest(tok.encode("utf-8"), self.server.token.encode("utf-8"))

    def _send(self, code: int, body: bytes, ctype: str, extra=None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    # -- GET ---------------------------------------------------------------
    def do_GET(self) -> None:
        if not self._host_ok():
            return self._json({"ok": False, "error": "bad host"}, 403)
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path in _STATIC:
            f = WEB / _STATIC[u.path]
            ctype = (mimetypes.guess_type(f.name)[0] or "text/plain") + "; charset=utf-8"
            csp = ("default-src 'none'; script-src 'self'; style-src 'self'; "
                   "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'")
            return self._send(200, f.read_bytes(), ctype, {"Content-Security-Policy": csp})
        if not self._token_ok(qs):
            return self._json({"ok": False, "error": "forbidden"}, 403)
        if u.path == "/api/state":
            return self._json({"ok": True, **self.server.session.state()})
        if u.path == "/api/settings":
            win = self.server.window
            return self._json({"ok": True, "settings": self.server.settings.get(), "version": __version__,
                               "window_available": bool(win and win.available())})
        if u.path == "/api/history":
            sh = self.server.shell
            return self._json({"ok": True, "history": sh.history if sh else []})
        if u.path == "/events":
            return self._events(qs)
        self._json({"ok": False, "error": "not found"}, 404)

    def _events(self, qs) -> None:
        srv = self.server
        try:
            since = int(self.headers.get("Last-Event-ID") or (qs.get("since") or ["0"])[0])
        except ValueError:
            since = 0
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        srv.client_connected()
        try:
            while not srv.closing and not self._peer_closed():
                evs = srv.session.events_since(since, timeout=1.0)
                if not evs:
                    self.wfile.write(b": ping\n\n")
                for i, payload in evs:
                    data = json.dumps(payload, ensure_ascii=False)
                    self.wfile.write(f"id: {i}\ndata: {data}\n\n".encode("utf-8"))
                    since = i
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            srv.client_gone()

    def _peer_closed(self) -> bool:
        """True once the browser has gone away (EOF waiting on the socket)."""
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
        except OSError:
            return True

    # -- POST --------------------------------------------------------------
    def do_POST(self) -> None:
        if not self._host_ok():
            return self._json({"ok": False, "error": "bad host"}, 403)
        u = urlparse(self.path)
        if not self._token_ok(parse_qs(u.query)):
            return self._json({"ok": False, "error": "forbidden"}, 403)
        if u.path == "/api/upload":
            return self._upload(parse_qs(u.query))
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            return self._json({"ok": False, "error": "bad size"}, 413)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._json({"ok": False, "error": "bad json"}, 400)
        sess = self.server.session
        try:
            if u.path == "/api/run":
                path = body.get("path") or sess.last_script
                if not isinstance(path, str) or not path:
                    return self._json({"ok": False, "error": "no script"})
                args = body.get("args") if isinstance(body.get("args"), list) else sess.last_args
                sh = self.server.shell
                if not os.path.isfile(path):
                    raise FileNotFoundError(path)
                if sh:       # picked file: work in its folder; plain re-run: stay where we are
                    sh.run_file(os.path.abspath(path), [str(a) for a in args], cd=bool(body.get("path")))
                else:
                    sess.start_script(path, [str(a) for a in args])
                return self._json({"ok": True})
            if u.path == "/api/repl":
                sh = self.server.shell
                sess.start_repl(sh.cwd if sh else None)
                return self._json({"ok": True})
            if u.path == "/api/shell":
                sh = self.server.shell
                if sh is None:
                    return self._json({"ok": False, "error": "shell disabled"})
                if sess.running():
                    return self._json({"ok": False, "error": "busy"})
                sh.execute(str(body.get("line", "")))
                return self._json({"ok": True})
            if u.path == "/api/complete":
                sh = self.server.shell
                if sh is None:
                    return self._json({"ok": False, "error": "shell disabled"})
                line = str(body.get("line", ""))
                try:
                    cur = int(body.get("cursor", len(line)))
                except (TypeError, ValueError):
                    cur = len(line)
                return self._json({"ok": True, **sh.complete(line, cur)})
            if u.path == "/api/settings":
                patch = body.get("patch") if isinstance(body.get("patch"), dict) else {}
                sh = self.server.shell
                if sh:
                    data = sh.apply_settings(patch)
                else:
                    data = self.server.settings.update(patch)
                return self._json({"ok": True, "settings": data})
            if u.path == "/api/window":
                win = self.server.window
                if win is None:
                    return self._json({"ok": False, "error": "unavailable", "available": False})
                return self._json(win.action(body))
            if u.path == "/api/watch":
                sh = self.server.shell
                if sh is None:
                    return self._json({"ok": False, "error": "shell disabled"})
                return self._json(sh.set_watch(bool(body.get("on"))))
            if u.path == "/api/drop":
                return self._json(self._drop(body))
            if u.path == "/api/stdin":
                text = str(body.get("text", ""))
                if body.get("normalize"):
                    text = fatext.normalize_input(text)
                return self._json({"ok": sess.send_input(text)})
            if u.path == "/api/stop":
                sess.stop()
                return self._json({"ok": True})
            if u.path == "/api/pick":
                return self._json(self._pick())
        except FileNotFoundError as e:
            return self._json({"ok": False, "error": f"فایل پیدا نشد: {e}"})
        except OSError as e:
            return self._json({"ok": False, "error": str(e)})
        self._json({"ok": False, "error": "not found"}, 404)

    def _drop(self, body: dict) -> dict:
        """Files dropped on the window: run the first script, otherwise insert the path(s)."""
        raw = body.get("files")
        if not isinstance(raw, list) or not raw:
            return {"ok": False, "error": "no files"}
        files = []
        for f in raw[:20]:
            try:
                files.append({"name": str(f["name"]), "size": int(f["size"]), "mtime": float(f["mtime"])})
            except (KeyError, TypeError, ValueError):
                return {"ok": False, "error": "bad file info"}
        sh, shift = self.server.shell, bool(body.get("shift"))
        roots = default_roots(sh.cwd if sh else None)
        first_py = next((i for i, f in enumerate(files) if f["name"].lower().endswith(SCRIPT_EXTS)), None)
        if first_py is not None and not shift:
            f = files[first_py]
            found = locate(f["name"], f["size"], f["mtime"], roots)
            if not found:
                return {"ok": True, "action": "upload", "index": first_py, "name": f["name"]}
            if sh:
                sh.run_file(found[0], cd=True)
            else:
                self.server.session.start_script(found[0])
            return {"ok": True, "action": "run", "path": found[0], "matches": len(found)}
        parts, missing = [], []
        for f in files:
            found = locate(f["name"], f["size"], f["mtime"], roots)
            if not found:
                missing.append(f["name"])
            parts.append(quote_path(found[0] if found else f["name"]))
        return {"ok": True, "action": "insert", "text": " ".join(parts) + " ", "missing": missing}

    def _upload(self, qs) -> None:
        """Fallback when a dropped script's real path is unknown: run a copy of its text."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        name = (qs.get("name") or [""])[0]
        if n < 0 or n > MAX_UPLOAD or safe_script_name(name) is None:
            return self._json({"ok": False, "error": "rejected"}, 400)
        data = self.rfile.read(n)
        try:
            path = save_upload(data, name, self.server.drop_dir)
        except (ValueError, OSError) as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        sh, sess = self.server.shell, self.server.session
        sess.write(f"\x1b[2mمسیر اصلی «{os.path.basename(path)}» پیدا نشد؛ نسخه‌ی کپی‌شده اجرا می‌شود "
                   f"(فایل‌های کنار آن در دسترس نیستند).\x1b[0m\n")
        if sh:
            sh.run_file(path, cd=False)
        else:
            sess.start_script(path)
        return self._json({"ok": True, "path": path})

    @staticmethod
    def _pick() -> dict:
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        try:
            r = subprocess.run([python_exe(), "-c", _PICK_CODE], capture_output=True,
                               text=True, encoding="utf-8", timeout=600, env=env)
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "error": str(e)}
        if r.returncode != 0:
            return {"ok": False, "error": "پنجره‌ی انتخاب فایل باز نشد (tkinter در دسترس نیست؟)"}
        path = r.stdout.strip()
        return {"ok": True, "path": path} if path else {"ok": False, "error": "", "cancelled": True}
