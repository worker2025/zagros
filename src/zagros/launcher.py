"""Open the console in a chromeless browser window (Edge/Chrome app mode)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser


def _candidates() -> list[str]:
    out: list[str] = []
    if sys.platform == "win32":
        roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        rel = (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe")
        out += [os.path.join(r, p) for r in roots if r for p in rel]
    elif sys.platform == "darwin":
        out += ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    for name in ("msedge", "microsoft-edge", "google-chrome", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            out.append(p)
    return out


def find_browser() -> str | None:
    for c in _candidates():
        if os.path.isfile(c):
            return c
    return None


def open_window(url: str, size: tuple[int, int] | None = None) -> bool:
    """Open ``url`` as a standalone app window; fall back to the default browser."""
    exe = find_browser()
    if exe:
        w, h = size or (960, 680)
        try:
            subprocess.Popen([exe, f"--app={url}", f"--window-size={w},{h}"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            pass
    return bool(webbrowser.open(url))
