import http.client
import json
import os
import tempfile
import threading
import time
import unittest

from tests.test_winctl import FakeApi
from zagros.server import ZagrosServer


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = os.path.realpath(tempfile.mkdtemp())
        cls.drops = os.path.join(tempfile.mkdtemp(), "dropped")
        cls.api = FakeApi()
        cls.srv = ZagrosServer(0, auto_exit=False, start_dir=cls.home, history_path=os.path.join(cls.home, ".h"),
                               settings_path=os.path.join(cls.home, ".s.json"), window_api=cls.api,
                               drop_dir=cls.drops)
        cls.port, cls.tok = cls.srv.port, cls.srv.token
        cls.api.add(1, f"iz — زاگرس · zagros:{cls.port}")
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()
        cls.srv.server_close()

    def setUp(self):
        self.srv.session.stop()
        self.srv.shell.cwd = self.home
        self.mark = self.srv.session._seq

    def call(self, method, path, body=None, raw=None, token=True, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        if token:
            h["X-FC-Token"] = self.tok
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        try:
            c.request(method, path, data, h)
            r = c.getresponse()
            out = r.read()
        finally:
            c.close()
        try:
            return r.status, json.loads(out)
        except ValueError:
            return r.status, out

    def events(self, until, timeout=10):
        end, last, got = time.time() + timeout, self.mark, []
        while time.time() < end:
            for i, e in self.srv.session.events_since(last, 0.3):
                last = i
                got.append(e)
            if until(got):
                return got
        raise AssertionError("timeout; tail=%r" % got[-5:])

    def text(self, evs):
        return "".join(e.get("s", "") for e in evs if e["t"] in ("out", "err"))

    def write(self, name, text="print('ok')\n", mtime=None):
        p = os.path.join(self.home, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        if mtime:
            os.utime(p, (mtime, mtime))
        return p


class SettingsEndpointTests(Base):
    def test_get_requires_token_and_reports_window_availability(self):
        self.assertEqual(self.call("GET", "/api/settings", token=False)[0], 403)
        st, r = self.call("GET", "/api/settings")
        self.assertTrue(r["ok"] and r["window_available"])
        self.assertEqual(r["settings"]["font"], 17)

    def test_post_validates_persists_and_notifies(self):
        st, r = self.call("POST", "/api/settings", {"patch": {"font": 99, "theme": "dark", "resultMode": True, "x": 1}})
        self.assertEqual((r["settings"]["font"], r["settings"]["theme"], r["settings"]["resultMode"]), (40, "dark", True))
        self.assertNotIn("x", r["settings"])
        ev = self.events(lambda g: any(e["t"] == "settings" for e in g))
        self.assertTrue(next(e for e in ev if e["t"] == "settings")["settings"]["resultMode"])
        with open(os.path.join(self.home, ".s.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["theme"], "dark")                      # survives restarts
        self.call("POST", "/api/settings", {"patch": {"resultMode": False, "theme": "auto", "font": 17}})
        self.assertEqual(self.call("POST", "/api/settings", {"patch": "garbage"})[1]["settings"]["font"], 17)

    def test_url_carries_result_mode_flag(self):
        s = ZagrosServer(0, auto_exit=False, shell=False, window=False, result_mode=True)
        try:
            self.assertTrue(s.url.endswith("&m=result"))
            self.assertFalse(self.srv.url.endswith("&m=result"))
        finally:
            s.server_close()

    def test_icon_is_served(self):
        st, body = self.call("GET", "/icon.svg", token=False)
        self.assertEqual(st, 200)
        self.assertIn(b"<svg", body)


class WindowEndpointTests(Base):
    def test_requires_token(self):
        self.assertEqual(self.call("POST", "/api/window", {"action": "state"}, token=False)[0], 403)

    def test_state_and_actions_via_the_marker_title(self):
        st, r = self.call("POST", "/api/window", {"action": "state"})
        self.assertTrue(r["available"] and r["found"])
        st, r = self.call("POST", "/api/window", {"action": "topmost", "on": True})
        self.assertTrue(r["ok"] and r["topmost"])
        st, r = self.call("POST", "/api/window", {"action": "preset", "name": "medium"})
        self.assertEqual((r["w"], r["h"]), (900, 600))
        st, r = self.call("POST", "/api/window", {"action": "size", "w": "x", "h": 1})
        self.assertEqual((r["ok"], r["error"]), (False, "bad arguments"))
        with open(os.path.join(self.home, ".s.json"), encoding="utf-8") as f:
            saved = json.load(f)["window"]
        self.assertEqual((saved["w"], saved["topmost"]), (900, True))
        self.call("POST", "/api/window", {"action": "topmost", "on": False})

    def test_disabled_window_control(self):
        s = ZagrosServer(0, auto_exit=False, shell=False, window=False)
        try:
            threading.Thread(target=s.serve_forever, daemon=True).start()
            c = http.client.HTTPConnection("127.0.0.1", s.port, timeout=5)
            c.request("POST", "/api/window", b"{}", {"X-FC-Token": s.token, "Host": f"127.0.0.1:{s.port}"})
            self.assertEqual(json.loads(c.getresponse().read())["available"], False)
        finally:
            s.close(); s.server_close()


class WatchEndpointTests(Base):
    def test_watch_on_off_and_error(self):
        self.srv.session.last_script = None
        self.assertEqual(self.call("POST", "/api/watch", {"on": True})[1]["error"], "no script")
        p = self.write("watched.py")
        self.call("POST", "/api/run", {"path": p})
        self.events(lambda g: any(e["t"] == "prompt" for e in g))
        r = self.call("POST", "/api/watch", {"on": True})[1]
        self.assertTrue(r["ok"] and r["active"])
        ev = self.events(lambda g: any(e["t"] == "watch" and e["on"] for e in g))
        self.assertTrue(ev)
        self.assertFalse(self.call("POST", "/api/watch", {"on": False})[1]["active"])

    def test_run_via_api_echoes_the_command(self):
        p = self.write("echo me.py")
        self.call("POST", "/api/run", {"path": p})
        ev = self.events(lambda g: any(e["t"] == "prompt" for e in g))
        self.assertIn(f'run "{p}"', self.text(ev))
        self.assertEqual(self.srv.shell.cwd, os.path.dirname(p))


class DropTests(Base):
    MT = 1_700_000_000

    def meta(self, path):
        st = os.stat(path)
        return {"name": os.path.basename(path), "size": st.st_size, "mtime": st.st_mtime * 1000}

    def test_dropped_script_is_located_and_run(self):
        p = self.write("sub/سلام دنیا.py", "print('dropped!')\n", mtime=self.MT)
        st, r = self.call("POST", "/api/drop", {"files": [self.meta(p)]})
        self.assertEqual((r["ok"], r["action"], r["path"]), (True, "run", p))
        ev = self.events(lambda g: any(e["t"] == "prompt" for e in g))
        out = self.text(ev)
        self.assertIn("dropped!", out)
        self.assertIn(f'run "{p}"', out)
        self.assertEqual(self.srv.shell.cwd, os.path.dirname(p))              # like double-clicking it

    def test_unknown_script_asks_for_upload_and_upload_runs_a_copy(self):
        f = {"name": "from-elsewhere.py", "size": 24, "mtime": 1.0}
        st, r = self.call("POST", "/api/drop", {"files": [f]})
        self.assertEqual((r["action"], r["index"], r["name"]), ("upload", 0, "from-elsewhere.py"))
        st, r = self.call("POST", "/api/upload?name=from-elsewhere.py", raw="print('copy ran')\n".encode(),
                          headers={"Content-Type": "application/octet-stream"})
        self.assertTrue(r["ok"])
        self.assertEqual(os.path.dirname(r["path"]), self.drops)
        ev = self.events(lambda g: any(e["t"] == "prompt" for e in g))
        out = self.text(ev)
        self.assertIn("copy ran", out)
        self.assertIn("نسخه‌ی کپی‌شده", out)
        self.assertEqual(self.srv.shell.cwd, self.home)                      # shell folder untouched

    def test_data_files_and_shift_insert_their_paths(self):
        a = self.write("data/my numbers.csv", "1,2\n", mtime=self.MT)
        b = self.write("plain.py", "x=1\n", mtime=self.MT)
        st, r = self.call("POST", "/api/drop", {"files": [self.meta(a), self.meta(b)], "shift": True})
        self.assertEqual(r["action"], "insert")
        self.assertEqual(r["text"], f'"{a}" {b} ')                           # quoted only when needed
        st, r = self.call("POST", "/api/drop", {"files": [self.meta(a)]})
        self.assertEqual(r["action"], "insert")                              # no .py -> insert, not run
        st, r = self.call("POST", "/api/drop", {"files": [{"name": "ghost.txt", "size": 1, "mtime": 1}]})
        self.assertEqual((r["text"], r["missing"]), ("ghost.txt ", ["ghost.txt"]))

    def test_bad_drop_payloads(self):
        for body in ({}, {"files": []}, {"files": "x"}, {"files": [{"name": "a.py"}]},
                     {"files": [{"name": "a.py", "size": "big", "mtime": 1}]}):
            st, r = self.call("POST", "/api/drop", body)
            self.assertFalse(r["ok"], body)
        self.assertEqual(self.call("POST", "/api/drop", {"files": [{}]}, token=False)[0], 403)

    def test_upload_is_locked_down(self):
        ok = b"print(1)\n"
        for name in ("evil.exe", "../../x.txt", "", "con.py", "a" * 200 + ".py"):
            st, r = self.call("POST", "/api/upload?name=" + name, raw=ok)
            self.assertEqual(st, 400, name)
        self.assertEqual(self.call("POST", "/api/upload?name=x.py", raw=ok, token=False)[0], 403)
        target = os.path.join(self.drops, "toobig.py")
        try:      # rejected before the body is read: either a 400 or the connection is cut
            st, r = self.call("POST", "/api/upload?name=toobig.py", raw=b"x" * 1_000_001)
            self.assertEqual(st, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.assertFalse(os.path.exists(target))                              # and nothing was saved
        st, r = self.call("POST", "/api/upload?name=../../escape.py", raw=ok)    # path part is stripped
        self.assertEqual(os.path.dirname(r["path"]), self.drops)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.drops), "escape.py")))
        self.srv.session.stop()


if __name__ == "__main__":
    unittest.main()
