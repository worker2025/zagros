"""A running child process plus an ordered, replayable event log."""
from __future__ import annotations

import codecs
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

_PKG = Path(__file__).resolve().parent
MAX_EVENTS = 5000


def python_exe() -> str:
    """``python.exe`` even if we were started from ``pythonw.exe``."""
    exe = sys.executable
    if os.path.basename(exe).lower() == "pythonw.exe":
        cand = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(cand):
            return cand
    return exe


def _kill_tree(proc: subprocess.Popen, force: bool = False) -> None:
    """Terminate ``proc`` *and its children* (shell commands, spawned helpers)."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                           timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            proc.kill()
        return
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.killpg(proc.pid, sig)  # child is its own session/process group leader
    except OSError:
        try:
            proc.send_signal(sig)
        except OSError:
            pass


class Session:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._events: list[tuple[int, dict]] = []
        self._seq = 0
        self._run = 0
        self._proc: subprocess.Popen | None = None
        self._wlock = threading.Lock()
        self.kind: str | None = None
        self.title = ""
        self.last_script: str | None = None
        self.last_args: list[str] = []
        self.shell_mode = False   # set by Shell: the UI then expects a "prompt" after each exit
        self.on_exit = None       # callable(code) invoked after a program ends on its own/Stop

    # -- event log ---------------------------------------------------------
    def _emit(self, run: int, **payload) -> None:
        with self._cond:
            self._seq += 1
            payload["run"] = run
            self._events.append((self._seq, payload))
            if len(self._events) > MAX_EVENTS:
                del self._events[: len(self._events) - MAX_EVENTS]
            self._cond.notify_all()

    def emit(self, **payload) -> None:
        """Shell-level event (run id 0): prompt, clear, ..."""
        self._emit(0, **payload)

    def write(self, text: str, err: bool = False, ltr: bool = False) -> None:
        """Shell-level output (not produced by a child process). ``ltr``: show the line left-to-right
        (file listings: a Persian name followed by ``.py`` must read like in Explorer)."""
        extra = {"ltr": True} if ltr else {}
        self._emit(0, t="err" if err else "out", s=text, **extra)

    def events_since(self, since: int, timeout: float = 10.0):
        end = time.monotonic() + timeout
        with self._cond:
            while True:
                out = [e for e in self._events if e[0] > since]
                if out:
                    return out
                left = end - time.monotonic()
                if left <= 0:
                    return []
                self._cond.wait(left)

    # -- control -----------------------------------------------------------
    def running(self) -> bool:
        p = self._proc
        return p is not None and p.poll() is None

    def state(self) -> dict:
        return {"running": self.running(), "kind": self.kind, "title": self.title,
                "run": self._run, "has_script": self.last_script is not None}

    def start_script(self, path: str, args=(), cwd: str | None = None) -> None:
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        self.last_script, self.last_args = path, list(args)
        cmd = [python_exe(), "-u", "-X", "utf8", str(_PKG / "_runner.py"), path, *args]
        self._launch(cmd, cwd or os.path.dirname(path), "script", os.path.basename(path))

    def start_repl(self, cwd: str | None = None) -> None:
        cmd = [python_exe(), "-u", "-X", "utf8", str(_PKG / "_repl.py")]
        self._launch(cmd, cwd or os.getcwd(), "repl", "Python")

    def start_command(self, cmd, cwd: str | None = None, title: str | None = None,
                      shell: bool = False) -> None:
        shown = title or (cmd if isinstance(cmd, str) else os.path.basename(cmd[0]))
        self._launch(cmd, cwd or os.getcwd(), "command", shown, shell=shell)

    def _launch(self, cmd, cwd, kind, title, shell: bool = False) -> None:
        self.stop(quiet=True)
        env = os.environ.copy()
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        kw: dict = {}
        if sys.platform == "win32":
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kw["start_new_session"] = True
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, shell=shell, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0, **kw)
        with self._cond:
            self._run += 1
            run = self._run
        self._proc = proc
        self.kind, self.title = kind, title
        self._emit(run, t="start", kind=kind, title=title, cwd=cwd)
        pumps = [threading.Thread(target=self._pump, args=(run, proc.stdout, "out"), daemon=True),
                 threading.Thread(target=self._pump, args=(run, proc.stderr, "err"), daemon=True)]
        for t in pumps:
            t.start()
        threading.Thread(target=self._watch, args=(run, proc, pumps, time.monotonic()),
                         daemon=True).start()

    def _pump(self, run, stream, name) -> None:
        dec = codecs.getincrementaldecoder("utf-8")("replace")
        fd = stream.fileno()
        while True:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            s = dec.decode(chunk)
            if s:
                self._emit(run, t=name, s=s)
        tail = dec.decode(b"", final=True)
        if tail:
            self._emit(run, t=name, s=tail)

    def _watch(self, run, proc, pumps, t0) -> None:
        code = proc.wait()
        for t in pumps:
            t.join(timeout=2)
        if not any(t.is_alive() for t in pumps):  # never close an fd a reader may still use
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    if stream:
                        stream.close()
                except OSError:
                    pass
        quiet = getattr(proc, "_fc_quiet", False)
        self._emit(run, t="exit", code=code, stopped=getattr(proc, "_fc_stopped", False),
                   elapsed=round(time.monotonic() - t0, 2), shell=self.shell_mode)
        if self.on_exit and not quiet and self._proc is proc:
            try:
                self.on_exit(code)
            except Exception:  # noqa: BLE001 - never kill the watcher thread
                pass

    def send_input(self, text: str) -> bool:
        p = self._proc
        if p is None or p.poll() is not None or p.stdin is None:
            return False
        try:
            with self._wlock:
                p.stdin.write(text.encode("utf-8"))
                p.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    def stop(self, quiet: bool = False) -> None:
        """Kill the running program (whole tree). ``quiet``: replaced by a new one, no prompt."""
        p = self._proc
        if p is None:
            return
        if quiet:
            p._fc_quiet = True
        if p.poll() is not None:
            return
        p._fc_stopped = True
        _kill_tree(p)
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _kill_tree(p, force=True)
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        try:
            if p.stdin:
                p.stdin.close()
        except OSError:
            pass
