import os
import tempfile
import time
import unittest

from zagros import winctl as w
from zagros.settings import Settings
from zagros.winctl import Rect, WindowController

MARK = "zagros:5000"


class FakeApi:
    """An in-memory Windows: top-level windows with invisible borders, DPI, styles, work area."""

    def __init__(self):
        self.win, self.calls = {}, []
        self.dpi_value = 96
        self.work = Rect(0, 0, 1920, 1040)
        self.frame_delta = (0, 0)           # extra shrink when WS_THICKFRAME is removed

    def add(self, hwnd, title, cls=w.CHROME_CLASS, rect=Rect(100, 100, 1114, 707), insets=(7, 0, 7, 7), visible=True):
        self.win[hwnd] = dict(title=title, cls=cls, rect=rect, insets=insets, visible=visible,
                              style=w.WS_THICKFRAME | w.WS_MAXIMIZEBOX | 0x00CF0000, ex=0, alpha=255,
                              iconic=False, zoomed=False)

    # --- queries
    def enum_windows(self):
        return [(h, v["title"], v["cls"]) for h, v in self.win.items() if v["visible"]]

    def is_window(self, h): return h in self.win
    def is_iconic(self, h): return self.win[h]["iconic"]
    def is_zoomed(self, h): return self.win[h]["zoomed"]
    def get_rect(self, h): return self.win[h]["rect"]
    def work_area(self, h): return self.work
    def dpi(self, h): return self.dpi_value

    def get_visible_rect(self, h):
        r, (l, t, rr, b) = self.win[h]["rect"], self.win[h]["insets"]
        return Rect(r.left + l, r.top + t, r.right - rr, r.bottom - b)

    def get_style(self, h, idx): return self.win[h]["style" if idx == w.GWL_STYLE else "ex"]

    # --- changes
    def set_style(self, h, idx, value):
        self.win[h]["style" if idx == w.GWL_STYLE else "ex"] = value

    def set_alpha(self, h, a): self.win[h]["alpha"] = a

    def set_pos(self, h, insert_after, x, y, ww, hh, flags):
        self.calls.append((h, insert_after, x, y, ww, hh, flags))
        v = self.win[h]
        r = v["rect"]
        if not flags & w.SWP_NOMOVE:
            r = Rect(x, y, x + r.width, y + r.height)
        if not flags & w.SWP_NOSIZE:
            r = Rect(r.left, r.top, r.left + ww, r.top + hh)
        if flags & w.SWP_FRAMECHANGED and not v["style"] & w.WS_THICKFRAME:
            r = Rect(r.left, r.top, r.right - self.frame_delta[0], r.bottom - self.frame_delta[1])
            self.frame_delta = (0, 0)
        v["rect"] = r
        if insert_after == w.HWND_TOPMOST:
            v["ex"] |= w.WS_EX_TOPMOST
        elif insert_after == w.HWND_NOTOPMOST:
            v["ex"] &= ~w.WS_EX_TOPMOST


def vis(api, h=1):
    return api.get_visible_rect(h)


class RectTests(unittest.TestCase):
    def test_clamp_rect(self):
        work = Rect(0, 0, 1000, 800)
        self.assertEqual(w.clamp_rect(Rect(5000, 5000, 5400, 5300), work), Rect(600, 500, 1000, 800))
        self.assertEqual(w.clamp_rect(Rect(-300, -50, 100, 250), work), Rect(0, 0, 400, 300))
        self.assertEqual(w.clamp_rect(Rect(0, 0, 3000, 3000), work), Rect(0, 0, 1000, 800))
        self.assertEqual(w.clamp_rect(Rect(10, 10, 110, 110), work), Rect(10, 10, 110, 110))

    def test_real_api_is_absent_off_windows(self):
        if os.name == "nt":
            self.skipTest("real Windows")
        self.assertIsNone(w.default_api())
        with self.assertRaises(OSError):
            w._Win32()


class ControllerCase(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.api.add(1, "iz — زاگرس · " + MARK)
        self.api.add(2, "some other tab", rect=Rect(0, 0, 500, 500))
        self.api.add(3, "زاگرس · " + MARK, cls="Notepad")           # right title, wrong class
        self.settings = Settings(os.path.join(tempfile.mkdtemp(), "s.json"))
        self.c = WindowController(MARK, self.api, self.settings, track_interval=0.05, enforce_interval=0.02)

    def tearDown(self):
        self.c.stop()


class FindTests(ControllerCase):
    def test_finds_only_the_matching_chromium_window(self):
        self.assertEqual(self.c.find(), 1)

    def test_not_found(self):
        self.api.win.pop(1)
        self.assertIsNone(self.c.find())
        self.assertEqual(self.c.state(), {"available": True, "found": False})

    def test_hidden_windows_are_ignored_and_new_window_is_found_after_close(self):
        self.api.win[1]["visible"] = False
        self.assertIsNone(self.c.find())
        self.api.win[1]["visible"] = True
        self.assertEqual(self.c.find(), 1)
        del self.api.win[1]
        self.api.add(9, "again " + MARK)
        self.assertEqual(self.c.find(), 9)

    def test_wait_finds_a_window_that_appears_later(self):
        self.api.win.pop(1)
        import threading
        threading.Timer(0.2, lambda: self.api.add(7, "late " + MARK)).start()
        self.assertEqual(self.c.find(wait=3, interval=0.05), 7)

    def test_unavailable_controller(self):
        c = WindowController(MARK, api=None)
        self.assertFalse(c.available())
        self.assertEqual(c.state(), {"available": False, "found": False})
        self.assertEqual(c.action({"action": "topmost", "on": True})["error"], "unavailable")


class TopmostOpacityTests(ControllerCase):
    def test_topmost_on_off(self):
        self.c.set_topmost(True)
        h, after, *_rest, flags = self.api.calls[-1]
        self.assertEqual((h, after, flags), (1, w.HWND_TOPMOST, w.SWP_NOMOVE | w.SWP_NOSIZE | w.SWP_NOACTIVATE))
        self.assertTrue(self.c.state()["topmost"])
        self.c.set_topmost(False)
        self.assertEqual(self.api.calls[-1][1], w.HWND_NOTOPMOST)
        self.assertFalse(self.c.state()["topmost"])

    def test_opacity(self):
        self.c.set_opacity(0.5)
        self.assertTrue(self.api.win[1]["ex"] & w.WS_EX_LAYERED)
        self.assertEqual(self.api.win[1]["alpha"], round(0.5 * 255))
        self.assertEqual(self.c.state()["opacity"], 0.5)
        self.c.set_opacity(0.0)                                  # floor: never invisible
        self.assertEqual(self.api.win[1]["alpha"], round(w.MIN_OPACITY * 255))
        self.c.set_opacity(1.0)                                  # opaque: plain window again
        self.assertFalse(self.api.win[1]["ex"] & w.WS_EX_LAYERED)

    def test_opacity_keeps_the_topmost_bit(self):
        self.c.set_topmost(True)
        self.c.set_opacity(0.6)
        self.assertTrue(self.api.win[1]["ex"] & w.WS_EX_TOPMOST)


class SizeTests(ControllerCase):
    def test_size_in_logical_pixels_with_invisible_borders(self):
        before = vis(self.api)
        self.c.set_size(900, 600)
        v = vis(self.api)
        self.assertEqual((v.width, v.height), (900, 600))             # what the user sees
        self.assertEqual((v.left, v.top), (before.left, before.top))  # stays where it was
        r = self.api.win[1]["rect"]
        self.assertEqual((r.width, r.height), (900 + 14, 600 + 7))    # +invisible borders
        self.assertEqual({k: self.c.state()[k] for k in ("w", "h")}, {"w": 900, "h": 600})

    def test_dpi_scaling(self):
        self.api.dpi_value = 120                                     # 125 %
        self.c.set_size(900, 600)
        v = vis(self.api)
        self.assertEqual((v.width, v.height), (1125, 750))
        st = self.c.state()
        self.assertEqual((st["w"], st["h"], st["scale"]), (900, 600, 1.25))

    def test_limits(self):
        self.c.set_size(10, 10)
        self.assertEqual((vis(self.api).width, vis(self.api).height), (w.MIN_W, w.MIN_H))
        self.c.set_size(9000, 9000)
        self.assertEqual((vis(self.api).width, vis(self.api).height), (1920, 1040))
        v = vis(self.api)
        self.assertGreaterEqual(v.left, 0)
        self.assertGreaterEqual(v.top, 0)

    def test_set_geometry_pulls_an_offscreen_window_back(self):
        self.c.set_geometry(5000, 5000, 800, 500)
        v = vis(self.api)
        self.assertEqual((v.right, v.bottom), (1920, 1040))
        self.c.set_geometry(-4000, -4000, 800, 500)
        v = vis(self.api)
        self.assertEqual((v.left, v.top), (0, 0))

    def test_snap(self):
        self.c.snap("left")
        self.assertEqual(vis(self.api), Rect(0, 0, 960, 1040))
        r = self.api.win[1]["rect"]
        self.assertEqual((r.left, r.right), (-7, 960 + 7))           # outer frame sticks out by the insets
        self.c.snap("right")
        self.assertEqual(vis(self.api), Rect(960, 0, 1920, 1040))
        self.c.snap("center")
        v = vis(self.api)
        self.assertEqual((v.width, v.height), w.PRESETS["medium"])
        self.assertEqual((v.left, v.top), ((1920 - 900) // 2, (1040 - 600) // 2))
        with self.assertRaises(ValueError):
            self.c.snap("diagonal")


class LockTests(ControllerCase):
    def test_lock_removes_resize_styles_and_keeps_the_size(self):
        self.api.frame_delta = (14, 7)                         # Windows shrinks the frame when the border goes
        before = self.api.win[1]["rect"]
        self.c.set_locked(True)
        st = self.api.win[1]["style"]
        self.assertFalse(st & w.WS_THICKFRAME)
        self.assertFalse(st & w.WS_MAXIMIZEBOX)
        now = self.api.win[1]["rect"]
        self.assertEqual((now.width, now.height), (before.width, before.height))   # restored after frame change
        self.assertTrue(self.c.state()["locked"])

    def test_enforcer_puts_the_size_back(self):
        self.c.set_locked(True)
        size = (self.api.win[1]["rect"].width, self.api.win[1]["rect"].height)
        self.assertFalse(self.c._enforce_once())               # nothing to fix
        r = self.api.win[1]["rect"]
        self.api.win[1]["rect"] = Rect(r.left, r.top, r.left + 700, r.top + 400)      # something resized it
        self.assertTrue(self.c._enforce_once())
        r = self.api.win[1]["rect"]
        self.assertEqual((r.width, r.height), size)

    def test_enforcer_thread_runs_and_unlock_stops_it(self):
        self.c.set_locked(True)
        r = self.api.win[1]["rect"]
        size = (r.width, r.height)
        self.api.win[1]["rect"] = Rect(r.left, r.top, r.left + 600, r.top + 300)
        end = time.time() + 3
        while (self.api.win[1]["rect"].width, self.api.win[1]["rect"].height) != size and time.time() < end:
            time.sleep(0.02)
        self.assertEqual((self.api.win[1]["rect"].width, self.api.win[1]["rect"].height), size)
        self.c.set_locked(False)
        self.assertTrue(self.api.win[1]["style"] & w.WS_THICKFRAME)
        self.assertTrue(self.api.win[1]["style"] & w.WS_MAXIMIZEBOX)
        self.api.win[1]["rect"] = Rect(0, 0, 640, 480)
        time.sleep(0.15)
        self.assertEqual(self.api.win[1]["rect"], Rect(0, 0, 640, 480))        # no longer enforced

    def test_explicit_resize_while_locked_is_allowed(self):
        self.c.set_locked(True)
        self.c.set_size(1000, 650)                               # user asked via the panel
        self.assertFalse(self.c._enforce_once())
        v = vis(self.api)
        self.assertEqual((v.width, v.height), (1000, 650))

    def test_enforcer_ignores_minimized_and_maximized(self):
        self.c.set_locked(True)
        self.api.win[1]["iconic"] = True
        self.api.win[1]["rect"] = Rect(-32000, -32000, -31840, -31972)
        self.assertFalse(self.c._enforce_once())


class ActionTests(ControllerCase):
    def test_actions_and_persistence(self):
        r = self.c.action({"action": "preset", "name": "large"})
        self.assertTrue(r["ok"])
        self.assertEqual((r["w"], r["h"]), w.PRESETS["large"])
        saved = self.settings.get()["window"]
        self.assertEqual((saved["w"], saved["h"]), w.PRESETS["large"])
        self.c.action({"action": "topmost", "on": True})
        self.c.action({"action": "opacity", "value": 0.8})
        self.assertTrue(self.settings.get()["window"]["topmost"])
        self.assertEqual(self.settings.get()["window"]["opacity"], 0.8)
        self.assertTrue(self.c.action({"action": "state"})["topmost"])

    def test_bad_input_never_raises(self):
        for body in ({"action": "size", "w": "abc", "h": 5}, {"action": "size"}, {"action": "preset", "name": "huge"},
                     {"action": "opacity", "value": "x"}, {"action": "snap", "side": "up"}):
            r = self.c.action(body)
            self.assertEqual((r["ok"], r["error"]), (False, "bad arguments"), body)
        self.assertEqual(self.c.action({"action": "nope"})["error"], "unknown action")

    def test_window_not_found_is_reported(self):
        self.api.win.pop(1)
        r = self.c.action({"action": "topmost", "on": True})
        self.assertEqual((r["ok"], r["error"]), (False, "window not found"))

    def test_win32_errors_are_contained(self):
        def boom(*a):
            raise OSError("access denied")
        self.api.set_pos = boom
        r = self.c.action({"action": "topmost", "on": True})
        self.assertFalse(r["ok"])
        self.assertIn("access denied", r["error"])


class RestoreAndTrackTests(ControllerCase):
    def test_apply_saved_restores_everything(self):
        self.c.apply_saved({"x": 50, "y": 60, "w": 800, "h": 500, "topmost": True, "opacity": 0.7, "locked": True})
        v = vis(self.api)
        self.assertEqual((v.left, v.top, v.width, v.height), (50, 60, 800, 500))
        self.assertTrue(self.api.win[1]["ex"] & w.WS_EX_TOPMOST)
        self.assertTrue(self.api.win[1]["ex"] & w.WS_EX_LAYERED)
        self.assertFalse(self.api.win[1]["style"] & w.WS_THICKFRAME)

    def test_apply_saved_with_nothing_saved_changes_nothing(self):
        before = dict(self.api.win[1])
        self.c.apply_saved({"w": None, "h": None, "topmost": False, "opacity": 1.0, "locked": False})
        self.assertEqual(self.api.win[1], before)

    def test_tracker_remembers_where_the_user_drags_the_window(self):
        self.c.attach_async({"w": 800, "h": 500, "x": 10, "y": 10})
        end = time.time() + 5
        while self.settings.get()["window"]["w"] != 800 and time.time() < end:
            time.sleep(0.02)
        self.assertEqual(self.settings.get()["window"]["w"], 800)
        r = self.api.win[1]["rect"]                              # user drags + resizes by hand
        self.api.win[1]["rect"] = Rect(300, 200, 300 + 1100, 200 + 700)
        end = time.time() + 5
        while self.settings.get()["window"]["x"] == 10 and time.time() < end:
            time.sleep(0.02)
        s = self.settings.get()["window"]
        self.assertEqual((s["x"], s["y"]), (307, 200))
        self.api.win[1]["iconic"] = True                         # minimized: must not store -32000
        self.api.win[1]["rect"] = Rect(-32000, -32000, -31840, -31972)
        time.sleep(0.3)
        self.assertGreater(self.settings.get()["window"]["x"], -1000)

    def test_tracker_stops_when_window_closes(self):
        self.c.attach_async({})
        time.sleep(0.2)
        del self.api.win[1]
        time.sleep(0.3)                                          # thread exits quietly; nothing to assert but no crash
        self.assertFalse(self.c.state()["found"])


if __name__ == "__main__":
    unittest.main()
