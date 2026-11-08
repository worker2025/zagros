"""Helpers for drag & drop: browsers only reveal a dropped file's name/size/mtime, not its path.

So we *find* the real file (name + size + modification time is practically unique) and, if that
fails, accept an upload of the script text as a fallback.
"""
from __future__ import annotations

import os
import re
import time
from collections import deque
from pathlib import Path

SCRIPT_EXTS = (".py", ".pyw")
_SKIP = {n.lower() for n in (
    "node_modules", "__pycache__", "venv", ".venv", "env", "site-packages", "AppData", "Windows",
    "Program Files", "Program Files (x86)", "$Recycle.Bin", "System Volume Information", "Library")}
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
MAX_UPLOAD = 1_000_000


def default_roots(cwd: str | None = None) -> list[str]:
    home = Path.home()
    cands = [cwd, home / "Desktop", home / "Downloads", home / "Documents", home]
    one = os.environ.get("OneDrive")
    if one:
        cands[3:3] = [Path(one) / "Desktop", Path(one) / "Documents"]
    out, seen = [], set()
    for c in cands:
        if c and os.path.isdir(c):
            key = os.path.realpath(c)
            if key not in seen:
                seen.add(key)
                out.append(str(c))
    return out


def locate(name: str, size: int, mtime_ms: float, roots, *, depth: int = 3, budget: float = 2.5,
           tol_ms: float = 2500, max_entries: int = 60000) -> list[str]:
    """Paths of files called ``name`` with the same size and (about) the same mtime.

    Roots are tried in priority order; the first root with a match wins. Bounded by ``depth``,
    ``budget`` seconds and ``max_entries`` so a huge disk can never hang the console.
    """
    want = re.split(r"[\\/]", str(name))[-1].lower()     # browsers send a bare name; be safe anyway
    deadline = time.monotonic() + budget
    entries = 0
    for root in roots:
        found: list[str] = []
        queue = deque([(str(root), 0)])
        while queue:
            folder, lvl = queue.popleft()
            try:
                it = os.scandir(folder)
            except OSError:
                continue
            with it:
                for e in it:
                    entries += 1
                    if entries > max_entries or time.monotonic() > deadline:
                        return found
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if lvl < depth and not e.name.startswith(".") and e.name.lower() not in _SKIP:
                                queue.append((e.path, lvl + 1))
                        elif e.name.lower() == want:
                            st = e.stat()
                            if st.st_size == size and abs(st.st_mtime * 1000 - mtime_ms) <= tol_ms:
                                found.append(e.path)
                    except OSError:
                        continue
        if found:
            return found
    return []


def safe_script_name(name: str) -> str | None:
    """A harmless file name for an uploaded script, or None."""
    base = re.split(r"[\\/]", str(name))[-1]
    base = re.sub(r'[\x00-\x1f<>:"|?*]', "_", base).strip(" .")
    stem, ext = os.path.splitext(base)
    if not stem or ext.lower() not in SCRIPT_EXTS or len(base) > 120:
        return None
    if stem.lower() in _RESERVED:
        return None
    return base


def save_upload(data: bytes, name: str, folder) -> str:
    safe = safe_script_name(name)
    if safe is None:
        raise ValueError("bad name")
    if len(data) > MAX_UPLOAD:
        raise ValueError("too large")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, safe)
    with open(path, "wb") as f:
        f.write(data)
    return path


def quote_path(p: str) -> str:
    return f'"{p}"' if re.search(r"\s", p) else p
