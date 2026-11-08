"""Native control of the console *window*: always on top, size presets, size lock, snapping,
opacity, and remembering the placement between launches.

A web page cannot do any of this, so the (Windows-only) work is done with the Win32 API through
``ctypes``. All decisions live in :class:`WindowController`; the raw API sits behind a tiny
interface (:class:`_Win32`) so the logic can be tested with a fake.
"""
from __future__ import annotations

import sys
import threading
import time
from typing import NamedTuple

HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x1, 0x2, 0x4, 0x10, 0x20
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_MAXIMIZEBOX, WS_THICKFRAME = 0x00010000, 0x00040000
WS_EX_TOPMOST, WS_EX_LAYERED = 0x00000008, 0x00080000
CHROME_CLASS = "Chrome_WidgetWin_1"          # Edge and Chrome top-level windows
PRESETS = {"small": (700, 450), "medium": (900, 600), "large": (1200, 800)}   # logical px
MIN_W, MIN_H = 360, 240
MIN_OPACITY = 0.3


class Rect(NamedTuple):
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def clamp_rect(r: Rect, work: Rect) -> Rect:
    """Shrink ``r`` to fit ``work`` and move it fully inside (e.g. after a monitor was unplugged)."""
    w, h = min(r.width, work.width), min(r.height, work.height)
    left = min(max(r.left, work.left), work.right - w)
    top = min(max(r.top, work.top), work.bottom - h)
    return Rect(left, top, left + w, top + h)


# --------------------------------------------------------------- real API ---
class _Win32:
    """Thin ctypes wrapper (Windows only). Everything else is plain Python."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Windows only")
        import ctypes
        from ctypes import wintypes as wt

        self.ct, self.wt = ctypes, wt
        u = self.u = ctypes.WinDLL("user32", use_last_error=True)
        try:   # physical pixels for windows of other (DPI-aware) processes
            u.SetProcessDpiAwarenessContext.argtypes = [wt.HANDLE]
            u.SetProcessDpiAwarenessContext(wt.HANDLE(-4))   # PER_MONITOR_AWARE_V2
        except (AttributeError, OSError):
            try:
                ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
            except (AttributeError, OSError):
                pass
        self._enum_proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        u.EnumWindows.argtypes = [self._enum_proc, wt.LPARAM]
        u.EnumWindows.restype = wt.BOOL
        for fn in ("IsWindow", "IsWindowVisible", "IsIconic", "IsZoomed", "GetWindowTextLengthW"):
            getattr(u, fn).argtypes = [wt.HWND]
        u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
        u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_uint]
        u.SetWindowPos.restype = wt.BOOL
        u.SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.COLORREF, ctypes.c_ubyte, wt.DWORD]
        u.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
        u.MonitorFromWindow.restype = wt.HANDLE
        if hasattr(u, "GetWindowLongPtrW"):                  # 64-bit
            self._get, self._set = u.GetWindowLongPtrW, u.SetWindowLongPtrW
            self._get.restype = self._set.restype = ctypes.c_ssize_t
            self._set.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
        else:                                                # 32-bit
            self._get, self._set = u.GetWindowLongW, u.SetWindowLongW
            self._get.restype = self._set.restype = ctypes.c_long
            self._set.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]
        self._get.argtypes = [wt.HWND, ctypes.c_int]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT),
                        ("dwFlags", wt.DWORD)]

        self._MONITORINFO = MONITORINFO
        u.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.POINTER(MONITORINFO)]
        try:
            self.dwm = ctypes.WinDLL("dwmapi")
            self.dwm.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
        except OSError:
            self.dwm = None

    # -- queries
    def _text(self, hwnd) -> str:
        n = self.u.GetWindowTextLengthW(hwnd)
        buf = self.ct.create_unicode_buffer(n + 1)
        self.u.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def _class(self, hwnd) -> str:
        buf = self.ct.create_unicode_buffer(256)
        self.u.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def enum_windows(self):
        out = []

        def cb(hwnd, _lparam):
            if self.u.IsWindowVisible(hwnd):
                out.append((hwnd, self._text(hwnd), self._class(hwnd)))
            return True

        self.u.EnumWindows(self._enum_proc(cb), 0)
        return out

    def is_window(self, h): return bool(self.u.IsWindow(h))
    def is_iconic(self, h): return bool(self.u.IsIconic(h))
    def is_zoomed(self, h): return bool(self.u.IsZoomed(h))

    def get_rect(self, h) -> Rect:
        r = self.wt.RECT()
        self.u.GetWindowRect(h, self.ct.byref(r))
        return Rect(r.left, r.top, r.right, r.bottom)

    def get_visible_rect(self, h) -> Rect:
        """Bounds without the invisible resize borders Windows 10/11 add around a window."""
        if self.dwm is not None:
            r = self.wt.RECT()
            if self.dwm.DwmGetWindowAttribute(h, 9, self.ct.byref(r), self.ct.sizeof(r)) == 0:  # EXTENDED_FRAME_BOUNDS
                return Rect(r.left, r.top, r.right, r.bottom)
        return self.get_rect(h)

    def work_area(self, h) -> Rect:
        mi = self._MONITORINFO()
        mi.cbSize = self.ct.sizeof(mi)
        self.u.GetMonitorInfoW(self.u.MonitorFromWindow(h, 2), self.ct.byref(mi))   # NEAREST
        w = mi.rcWork
        return Rect(w.left, w.top, w.right, w.bottom)

    def dpi(self, h) -> int:
        try:
            return int(self.u.GetDpiForWindow(h)) or 96
        except (AttributeError, OSError):
            return 96

    # -- changes
    def set_pos(self, h, insert_after, x, y, w, hh, flags) -> None:
        self.u.SetWindowPos(h, insert_after or 0, x, y, w, hh, flags)

    def get_style(self, h, index) -> int:
        return int(self._get(h, index))

    def set_style(self, h, index, value) -> None:
        self._set(h, index, value)

    def set_alpha(self, h, alpha) -> None:
        self.u.SetLayeredWindowAttributes(h, 0, alpha, 2)    # LWA_ALPHA


def default_api():
    try:
        return _Win32()
    except Exception:  # noqa: BLE001 - not Windows, or API unavailable
        return None


# ------------------------------------------------------------- controller ---
class WindowController:
    def __init__(self, marker: str, api="auto", settings=None, *, track_interval: float = 1.5,
                 enforce_interval: float = 0.25) -> None:
        self.marker = marker
        self.api = default_api() if api == "auto" else api
        self.settings = settings
        self.track_interval, self.enforce_interval = track_interval, enforce_interval
        self._hwnd = None
        self._lock = threading.RLock()
        self._locked = False
        self._locked_size: tuple[int, int] | None = None
        self._opacity = 1.0
        self._stop = threading.Event()
        self._last_saved = None

    def available(self) -> bool:
        return self.api is not None

    # -- finding the window ------------------------------------------------
    def _find_once(self):
        if not self.api:
            return None
        with self._lock:
            if self._hwnd and self.api.is_window(self._hwnd):
                return self._hwnd
            self._hwnd = None
            for hwnd, title, cls in self.api.enum_windows():
                if cls == CHROME_CLASS and self.marker in title:
                    self._hwnd = hwnd
                    return hwnd
        return None

    def find(self, wait: float = 0.0, interval: float = 0.25):
        end = time.monotonic() + wait
        while True:
            h = self._find_once()
            if h or time.monotonic() >= end or self._stop.is_set():
                return h
            time.sleep(interval)

    # -- geometry helpers --------------------------------------------------
    def _scale(self, h) -> float:
        return max(self.api.dpi(h), 96) / 96

    def _insets(self, h):
        r, v = self.api.get_rect(h), self.api.get_visible_rect(h)
        return (max(0, v.left - r.left), max(0, v.top - r.top),
                max(0, r.right - v.right), max(0, r.bottom - v.bottom))

    def _place(self, h, vis: Rect) -> None:
        """Move/resize so the *visible* frame equals ``vis`` (pixels)."""
        l, t, r, b = self._insets(h)
        w, hh = vis.width + l + r, vis.height + t + b
        if self._locked:
            self._locked_size = (w, hh)       # before the call, so the enforcer never undoes it
        self.api.set_pos(h, 0, vis.left - l, vis.top - t, w, hh, SWP_NOZORDER | SWP_NOACTIVATE)

    def _visible(self, h) -> Rect:
        return self.api.get_visible_rect(h)

    def set_geometry(self, x, y, w, hh) -> None:
        """Logical (96-dpi) pixels; ``x``/``y`` may be None to keep the current position."""
        h = self._need()
        s, work = self._scale(h), self.api.work_area(h)
        cur = self._visible(h)
        pw = round(max(MIN_W, w) * s)
        ph = round(max(MIN_H, hh) * s)
        left = round(x * s) if x is not None else cur.left
        top = round(y * s) if y is not None else cur.top
        self._place(h, clamp_rect(Rect(left, top, left + pw, top + ph), work))

    def set_size(self, w: int, hh: int) -> None:
        self.set_geometry(None, None, int(w), int(hh))

    def snap(self, side: str) -> None:
        h = self._need()
        wa, s = self.api.work_area(h), self._scale(h)
        half = wa.width // 2
        if side == "left":
            target = Rect(wa.left, wa.top, wa.left + half, wa.bottom)
        elif side == "right":
            target = Rect(wa.right - half, wa.top, wa.right, wa.bottom)
        elif side == "center":
            pw, ph = (round(v * s) for v in PRESETS["medium"])
            pw, ph = min(pw, wa.width), min(ph, wa.height)
            left, top = wa.left + (wa.width - pw) // 2, wa.top + (wa.height - ph) // 2
            target = Rect(left, top, left + pw, top + ph)
        else:
            raise ValueError("side")
        self._place(h, target)

    # -- toggles -----------------------------------------------------------
    def set_topmost(self, on: bool) -> None:
        h = self._need()
        self.api.set_pos(h, HWND_TOPMOST if on else HWND_NOTOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def set_opacity(self, value: float) -> None:
        h = self._need()
        a = max(MIN_OPACITY, min(1.0, float(value)))
        ex = self.api.get_style(h, GWL_EXSTYLE)
        if a >= 0.999:
            self.api.set_style(h, GWL_EXSTYLE, ex & ~WS_EX_LAYERED)      # fully opaque: plain window
        else:
            self.api.set_style(h, GWL_EXSTYLE, ex | WS_EX_LAYERED)
            self.api.set_alpha(h, round(a * 255))
        self._opacity = round(a, 2)

    def set_locked(self, on: bool) -> None:
        h = self._need()
        refresh = SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
        style = self.api.get_style(h, GWL_STYLE)
        if on:
            before = self.api.get_rect(h)
            self.api.set_style(h, GWL_STYLE, style & ~(WS_THICKFRAME | WS_MAXIMIZEBOX))
            self.api.set_pos(h, 0, 0, 0, 0, 0, refresh)
            with self._lock:
                self._locked, self._locked_size = True, (before.width, before.height)
            now = self.api.get_rect(h)
            if (now.width, now.height) != self._locked_size:             # frame change shifted the size
                self.api.set_pos(h, 0, now.left, now.top, *self._locked_size, SWP_NOZORDER | SWP_NOACTIVATE)
            threading.Thread(target=self._enforce_loop, daemon=True).start()
        else:
            with self._lock:
                self._locked, self._locked_size = False, None
            self.api.set_style(h, GWL_STYLE, style | WS_THICKFRAME | WS_MAXIMIZEBOX)
            self.api.set_pos(h, 0, 0, 0, 0, 0, refresh)

    def _enforce_once(self) -> bool:
        """Safety net: if something still resized a locked window, put the size back."""
        with self._lock:
            h = self._hwnd
            if not (self._locked and self._locked_size and h and self.api.is_window(h)):
                return False
            if self.api.is_iconic(h) or self.api.is_zoomed(h):
                return False
            r = self.api.get_rect(h)
            if (r.width, r.height) == self._locked_size:
                return False
            self.api.set_pos(h, 0, r.left, r.top, *self._locked_size, SWP_NOZORDER | SWP_NOACTIVATE)
            return True

    def _enforce_loop(self) -> None:
        while self._locked and not self._stop.wait(self.enforce_interval):
            if self._hwnd and not self.api.is_window(self._hwnd):
                break
            self._enforce_once()

    # -- state / actions ---------------------------------------------------
    def _need(self):
        h = self._find_once()
        if not h:
            raise LookupError("window not found")
        return h

    def state(self) -> dict:
        if not self.api:
            return {"available": False, "found": False}
        h = self._find_once()
        if not h:
            return {"available": True, "found": False}
        s, v, work = self._scale(h), self._visible(h), self.api.work_area(h)
        return {"available": True, "found": True, "scale": s,
                "topmost": bool(self.api.get_style(h, GWL_EXSTYLE) & WS_EX_TOPMOST),
                "locked": self._locked, "opacity": self._opacity,
                "x": round(v.left / s), "y": round(v.top / s), "w": round(v.width / s), "h": round(v.height / s),
                "work": {"w": round(work.width / s), "h": round(work.height / s)}}

    def action(self, body: dict) -> dict:
        if not self.api:
            return {"ok": False, "error": "unavailable", **self.state()}
        a = body.get("action", "state")
        if a != "state":
            if not self._find_once():
                return {"ok": False, "error": "window not found", **self.state()}
            try:
                if a == "topmost":
                    self.set_topmost(bool(body.get("on")))
                elif a == "size":
                    self.set_size(int(body["w"]), int(body["h"]))
                elif a == "preset":
                    self.set_size(*PRESETS[body["name"]])
                elif a == "snap":
                    self.snap(str(body.get("side")))
                elif a == "lock":
                    self.set_locked(bool(body.get("on")))
                elif a == "opacity":
                    self.set_opacity(float(body["value"]))
                else:
                    return {"ok": False, "error": "unknown action"}
            except (KeyError, ValueError, TypeError):
                return {"ok": False, "error": "bad arguments"}
            except Exception as e:  # noqa: BLE001 - a Win32 hiccup must not crash the server
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}
            self._persist()
        return {"ok": True, **self.state()}

    # -- persistence -------------------------------------------------------
    def _snapshot(self):
        st = self.state()
        if not st.get("found"):
            return None
        return {k: st[k] for k in ("x", "y", "w", "h", "topmost", "locked", "opacity")}

    def _persist(self) -> None:
        snap = self._snapshot()
        if snap and self.settings is not None and snap != self._last_saved:
            self._last_saved = snap
            self.settings.update({"window": snap})

    def apply_saved(self, saved: dict) -> None:
        if saved.get("w") and saved.get("h"):
            self.set_geometry(saved.get("x"), saved.get("y"), saved["w"], saved["h"])
        if saved.get("opacity", 1.0) < 1.0:
            self.set_opacity(saved["opacity"])
        if saved.get("topmost"):
            self.set_topmost(True)
        if saved.get("locked"):
            self.set_locked(True)

    def attach_async(self, saved: dict | None = None) -> None:
        """After the browser window opens: restore last placement, then keep remembering it."""
        threading.Thread(target=self._attach, args=(saved or {},), daemon=True).start()

    def _attach(self, saved: dict) -> None:
        if not self.find(wait=20):
            return
        try:
            self.apply_saved(saved)
        except Exception:  # noqa: BLE001
            pass
        while not self._stop.wait(self.track_interval):      # remember where the user drags it
            h = self._hwnd
            if not h or not self.api.is_window(h):
                break
            if self.api.is_iconic(h) or self.api.is_zoomed(h):
                continue
            self._persist()

    def stop(self) -> None:
        self._stop.set()
