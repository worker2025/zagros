"""Re-run a script whenever it is saved (edit in any editor, watch the result here)."""
from __future__ import annotations

import os
import threading
import time


def _sig(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None            # editors briefly remove/rename the file while saving
    return (st.st_mtime_ns, st.st_size)


class Watcher:
    def __init__(self, on_change, interval: float = 0.4, settle: float = 0.3) -> None:
        self.on_change, self.interval, self.settle = on_change, interval, settle
        self.path: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last = None

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def start(self, path: str) -> None:
        self.stop()
        self.path, self._last = path, _sig(path)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, args=(self._stop,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=2)
        self._thread = None

    def _loop(self, stop: threading.Event) -> None:
        while not stop.wait(self.interval):
            sig = _sig(self.path)
            if sig is None or sig == self._last:
                continue
            if stop.wait(self.settle):          # let the editor finish writing
                return
            again = _sig(self.path)
            if again != sig:
                self._last = None               # still changing: look again next round
                continue
            self._last = sig
            try:
                self.on_change(self.path)
            except Exception:  # noqa: BLE001 - never kill the watcher
                pass
