import http.client
import json
import os
import tempfile
import threading
import time
import unittest

from zagros.server import ZagrosServer


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp()
        cls.srv = ZagrosServer(0, auto_exit=False, start_dir=cls.home,
                              history_path=os.path.join(cls.home, '.h'))
        cls.port = cls.srv.port
        cls.tok = cls.srv.token
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()
        cls.srv.server_close()

    def req(self, method, path, body=None, token=True, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if token:
            h["X-FC-Token"] = self.tok
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        c.request(method, path, data, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, r.getheaders(), raw

    def setUp(self):
        # every test starts idle, in a clean folder, and only looks at events it caused
        self.srv.session.stop()
        self.srv.shell.cwd = os.path.realpath(self.home)
        self.mark = self.srv.session._seq

    def events(self, until, timeout=10, since=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        c.request("GET", f"/events?since={self.mark if since is None else since}&t={self.tok}")
        r = c.getresponse()
        got, end = [], time.time() + timeout
        while time.time() < end:
            line = r.fp.readline().decode("utf-8")
            if line.startswith("data: "):
                got.append(json.loads(line[6:]))
                if until(got):
                    break
        c.close()
        return got

    def script(self, src):
        p = os.path.join(tempfile.mkdtemp(), "p.py")
        with open(p, "w", encoding="utf-8") as f:
            f.write(src)
        return p

    # -- security ----------------------------------------------------------
    def test_api_requires_token(self):
        self.assertEqual(self.req("GET", "/api/state", token=False)[0], 403)
        self.assertEqual(self.req("POST", "/api/stop", {}, token=False)[0], 403)
        self.assertEqual(self.req("GET", "/events?since=0", token=False)[0], 403)

    def test_token_in_query_is_accepted_for_get(self):
        self.assertEqual(self.req("GET", f"/api/state?t={self.tok}", token=False)[0], 200)

    def test_wrong_token_rejected(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/api/state", headers={"X-FC-Token": "nope", "Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(c.getresponse().status, 403)

    def test_bad_host_rejected_even_with_token(self):
        self.assertEqual(self.req("GET", "/api/state", host="evil.example:80")[0], 403)
        self.assertEqual(self.req("GET", "/", host="evil.example:80")[0], 403)

    def test_no_cors_and_no_options(self):
        st, hdrs, _ = self.req("GET", "/api/state")
        self.assertFalse(any(k.lower().startswith("access-control") for k, _ in hdrs))
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("OPTIONS", "/api/run", headers={"Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(c.getresponse().status, 501)

    def test_body_limits_and_bad_json(self):
        self.assertEqual(self.req("POST", "/api/stdin", {"text": "x" * 70000})[0], 413)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", "/api/stdin", b"{not json",
                  {"X-FC-Token": self.tok, "Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(c.getresponse().status, 400)

    def test_static_files_and_csp(self):
        st, hdrs, body = self.req("GET", "/", token=False)
        self.assertEqual(st, 200)
        self.assertIn("زاگرس", body.decode("utf-8"))
        csp = dict(hdrs)["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        for p in ("/console.js", "/style.css"):
            self.assertEqual(self.req("GET", p, token=False)[0], 200)
        self.assertEqual(self.req("GET", "/etc/passwd", token=False)[0], 403)

    def test_html_has_no_inline_script_or_style(self):
        html = self.req("GET", "/", token=False)[2].decode("utf-8")
        self.assertNotIn("<style", html)
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)")
        self.assertNotIn(" style=", html)

    # -- behaviour ---------------------------------------------------------
    def test_run_stdin_normalize_and_events(self):
        p = self.script("x = input('n: ')\nprint(repr(x))\n")
        self.assertTrue(json.loads(self.req("POST", "/api/run", {"path": p})[2])["ok"])
        got = []
        t = threading.Thread(target=lambda: got.extend(
            self.events(lambda g: any(e["t"] == "exit" for e in g))))
        t.start()
        time.sleep(0.8)
        r = self.req("POST", "/api/stdin", {"text": "۱۲٫۵\n", "normalize": True})
        self.assertTrue(json.loads(r[2])["ok"])
        t.join(15)
        out = "".join(e.get("s", "") for e in got if e["t"] == "out" and e["run"] == got[-1]["run"])
        self.assertIn("'12.5'", out)

    def test_stdin_without_normalize_keeps_text(self):
        p = self.script("print(repr(input()))\n")
        self.req("POST", "/api/run", {"path": p})
        time.sleep(0.6)
        self.req("POST", "/api/stdin", {"text": "۱۲\n", "normalize": False})
        got = self.events(lambda g: any(e["t"] == "exit" for e in g))
        self.assertTrue(any("'۱۲'" in e.get("s", "") for e in got))

    def test_run_missing_file_reports_error(self):
        r = json.loads(self.req("POST", "/api/run", {"path": "/nope/zzz.py"})[2])
        self.assertFalse(r["ok"])

    def test_rerun_without_script(self):
        srv = ZagrosServer(0, auto_exit=False)
        try:
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
            c.request("POST", "/api/run", b"{}", {"X-FC-Token": srv.token, "Host": f"127.0.0.1:{srv.port}"})
            self.assertEqual(json.loads(c.getresponse().read())["error"], "no script")
        finally:
            srv.close(); srv.server_close()

    def test_stop_endpoint(self):
        p = self.script("import time\nprint('up', flush=True)\ntime.sleep(60)\n")
        self.req("POST", "/api/run", {"path": p})
        time.sleep(0.6)
        self.assertTrue(self.srv.session.running())
        self.req("POST", "/api/stop", {})
        time.sleep(0.5)
        self.assertFalse(self.srv.session.running())

    # -- shell endpoints -----------------------------------------------------
    def wait_idle(self):
        end = time.time() + 10
        while self.srv.session.running() and time.time() < end:
            time.sleep(0.05)

    def test_shell_endpoints_require_token(self):
        for path in ("/api/shell", "/api/complete"):
            self.assertEqual(self.req("POST", path, {"line": "help"}, token=False)[0], 403)
        self.assertEqual(self.req("GET", "/api/history", token=False)[0], 403)

    def test_shell_runs_builtin_and_emits_prompt(self):
        last = self.srv.session._seq
        r = json.loads(self.req("POST", "/api/shell", {"line": "pwd"})[2])
        self.assertTrue(r["ok"])
        evs = [e for i, e in self.srv.session.events_since(last, 3)]
        self.assertIn(os.path.realpath(self.home), "".join(e.get("s", "") for e in evs if e["t"] == "out").replace("\n", ""))
        self.assertEqual(evs[-1]["t"], "prompt")

    def test_shell_runs_file_by_name_and_history_endpoint(self):
        self.wait_idle()
        with open(os.path.join(self.home, "تست.py"), "w", encoding="utf-8") as f:
            f.write("print('ok-from-shell')\n")
        self.req("POST", "/api/shell", {"line": "تست.py"})
        got = self.events(lambda g: any("ok-from-shell" in e.get("s", "") for e in g))
        self.assertTrue(any("ok-from-shell" in e.get("s", "") for e in got))
        self.wait_idle()
        hist = json.loads(self.req("GET", "/api/history")[2])["history"]
        self.assertIn("تست.py", hist)

    def test_shell_busy_while_program_runs(self):
        self.wait_idle()
        p = self.script("import time\nprint('up', flush=True)\ntime.sleep(60)\n")
        self.req("POST", "/api/run", {"path": p})
        time.sleep(0.6)
        r = json.loads(self.req("POST", "/api/shell", {"line": "pwd"})[2])
        self.assertEqual(r, {"ok": False, "error": "busy"})
        self.req("POST", "/api/stop", {})
        self.wait_idle()

    def test_complete_endpoint(self):
        open(os.path.join(self.home, "zeta_file.py"), "w").close()
        r = json.loads(self.req("POST", "/api/complete", {"line": "run zeta", "cursor": 8})[2])
        self.assertTrue(r["ok"])
        self.assertEqual(r["replacement"], "zeta_file.py ")
        r = json.loads(self.req("POST", "/api/complete", {"line": "run zeta", "cursor": "bad"})[2])
        self.assertTrue(r["ok"])

    def test_picked_file_moves_shell_into_its_folder(self):
        self.wait_idle()
        p = self.script("import os\nprint(os.getcwd())\n")
        self.req("POST", "/api/run", {"path": p})
        self.wait_idle()
        self.assertEqual(self.srv.shell.cwd, os.path.dirname(os.path.abspath(p)))

    def test_shell_disabled_mode(self):
        srv = ZagrosServer(0, auto_exit=False, shell=False)
        try:
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
            c.request("POST", "/api/shell", b'{"line":"pwd"}', {"X-FC-Token": srv.token, "Host": f"127.0.0.1:{srv.port}"})
            self.assertEqual(json.loads(c.getresponse().read())["error"], "shell disabled")
        finally:
            srv.close(); srv.server_close()

    def test_watchdog_shuts_server_when_browser_closes(self):
        srv = ZagrosServer(0, grace=0.5)
        done = threading.Event()
        threading.Thread(target=lambda: (srv.serve_forever(), done.set()), daemon=True).start()
        c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        c.request("GET", f"/events?since=0&t={srv.token}")
        c.getresponse()
        time.sleep(0.3)
        c.close()                       # the "window" goes away
        self.assertTrue(done.wait(5), "server did not stop after client left")
        srv.server_close()


if __name__ == "__main__":
    unittest.main()
