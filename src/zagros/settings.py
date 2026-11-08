"""User preferences stored server-side (a random port means a new browser origin every launch,
so ``localStorage`` cannot remember anything)."""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

DEFAULTS = {
    "font": 17, "theme": "auto", "normalize": True, "faDigits": False,
    "resultMode": False, "resultFont": 52,      # "big result" mode: output only, very large
    "window": {"topmost": False, "locked": False, "opacity": 1.0,
               "w": None, "h": None, "x": None, "y": None},
}


def _int(v, lo, hi, default):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    return max(lo, min(hi, int(v)))


def _opt_int(v, lo, hi):
    return None if v is None else _int(v, lo, hi, None)


def _bool(v, default):
    return v if isinstance(v, bool) else default


def _validate(cur: dict, patch: dict) -> dict:
    """Return ``cur`` updated with every *known and valid* key of ``patch``."""
    out = copy.deepcopy(cur)
    if "font" in patch:
        out["font"] = _int(patch["font"], 10, 40, out["font"])
    if "resultFont" in patch:
        out["resultFont"] = _int(patch["resultFont"], 20, 200, out["resultFont"])
    if patch.get("theme") in ("auto", "dark", "light"):
        out["theme"] = patch["theme"]
    for k in ("normalize", "faDigits", "resultMode"):
        if k in patch:
            out[k] = _bool(patch[k], out[k])
    w = patch.get("window")
    if isinstance(w, dict):
        ow = out["window"]
        for k in ("topmost", "locked"):
            if k in w:
                ow[k] = _bool(w[k], ow[k])
        if "opacity" in w and isinstance(w["opacity"], (int, float)) and not isinstance(w["opacity"], bool):
            ow["opacity"] = round(max(0.3, min(1.0, float(w["opacity"]))), 2)
        for k, lo, hi in (("w", 200, 10000), ("h", 150, 10000), ("x", -32000, 32000), ("y", -32000, 32000)):
            if k in w:
                ow[k] = _opt_int(w[k], lo, hi) if w[k] is not None else None
    return out


class Settings:
    def __init__(self, path=None) -> None:
        self.path = Path(path or os.environ.get("ZAGROS_SETTINGS") or Path.home() / ".zagros_settings.json")
        self._lock = threading.Lock()
        self.data = copy.deepcopy(DEFAULTS)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data = _validate(self.data, loaded)
        except (OSError, ValueError):
            pass

    def get(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.data)

    def update(self, patch: dict) -> dict:
        with self._lock:
            self.data = _validate(self.data, patch if isinstance(patch, dict) else {})
            tmp = self.path.with_name(self.path.name + ".tmp")
            try:
                tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
                os.replace(tmp, self.path)
            except OSError:
                pass
            return copy.deepcopy(self.data)
