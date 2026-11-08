import json
import os
import re
import subprocess
import sys
import tempfile
import http.client
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")


def env():
    e = dict(os.environ)
    e["PYTHONPATH"] = SRC + os.pathsep + e.get("PYTHONPATH", "")
    e["PYTHONUTF8"] = "1"
    return e


class CliTests(unittest.TestCase):
    def test_version(self):
        r = subprocess.run([sys.executable, "-m", "zagros", "--version"],
                           capture_output=True, text=True, env=env())
        self.assertEqual(r.returncode, 0)
        self.assertIn("zagros 0.3.0", r.stdout)

    def test_missing_script_exit_code(self):
        r = subprocess.run([sys.executable, "-m", "zagros", "--no-browser", "/nope/x.py"],
                           capture_output=True, text=True, env=env(), timeout=20)
        self.assertEqual(r.returncode, 2)

    def start(self, *args, cwd=None):
        p = subprocess.Popen([sys.executable, "-m", "zagros", "--no-browser", *args],
                             stdout=subprocess.PIPE, text=True, encoding="utf-8", env=env(), cwd=cwd)
        m = re.search(r"http://127\.0\.0\.1:(\d+)/\?t=([\w-]+)", p.stdout.readline())
        self.assertIsNotNone(m)
        return p, int(m.group(1)), m.group(2)

    @staticmethod
    def read_events(port, tok, until, timeout=15):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        c.request("GET", f"/events?since=0&t={tok}")
        r = c.getresponse()
        seen = []
        while True:
            ln = r.fp.readline().decode("utf-8")
            if ln.startswith("data: "):
                seen.append(json.loads(ln[6:]))
                if until(seen):
                    return seen, r, c

    @staticmethod
    def post(port, tok, path, body):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("POST", path, json.dumps(body), {"X-FC-Token": tok})
        out = json.loads(c.getresponse().read())
        c.close()
        return out

    def test_default_is_an_idle_shell_with_welcome_and_prompt(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "سلام.py"), "w", encoding="utf-8") as f:
            f.write("print('hi from file')\n")
        p, port, tok = self.start(cwd=d)
        try:
            seen, r, c = self.read_events(port, tok, lambda s: any(e["t"] == "prompt" for e in s))
            text = "".join(e.get("s", "") for e in seen if e["t"] == "out")
            self.assertIn("کنسول فارسی", text)
            self.assertFalse(any(e["t"] == "start" for e in seen))        # nothing running yet
            self.assertEqual(os.path.realpath(seen[-1]["cwd"]), os.path.realpath(d))
            r.close(); c.close()
            # type the file name, like a learner would
            self.assertTrue(self.post(port, tok, "/api/shell", {"line": "سلام.py"})["ok"])
            seen, r, c = self.read_events(port, tok, lambda s: sum(e["t"] == "prompt" for e in s) == 2)
            self.assertIn("hi from file", "".join(e.get("s", "") for e in seen if e["t"] == "out"))
            self.post(port, tok, "/api/shell", {"line": "exit"})
            r.close(); c.close()
            p.wait(timeout=20)
            self.assertEqual(p.returncode, 0)                              # `exit` closes everything
        finally:
            if p.poll() is None:
                p.kill()
            p.wait()
            p.stdout.close()

    def test_script_argument_runs_then_drops_to_prompt(self):
        d = tempfile.mkdtemp()
        script = os.path.join(d, "a.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write("import os\nprint('cwd=' + os.getcwd())\n")
        p, port, tok = self.start(script, cwd=tempfile.gettempdir())
        try:
            seen, r, c = self.read_events(port, tok, lambda s: any(e["t"] == "prompt" for e in s))
            out = "".join(e.get("s", "") for e in seen if e["t"] == "out")
            self.assertIn("cwd=" + os.path.realpath(tempfile.gettempdir()), os.path.realpath(out.split("cwd=")[1].strip()) and out)
            r.close(); c.close()
        finally:
            p.kill(); p.wait(); p.stdout.close()

    def test_chdir_script_flag_uses_the_scripts_folder(self):
        d = os.path.realpath(tempfile.mkdtemp())
        script = os.path.join(d, "a.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write("import os\nprint('cwd=' + os.getcwd())\n")
        p, port, tok = self.start("--chdir-script", script, cwd=tempfile.gettempdir())
        try:
            seen, r, c = self.read_events(port, tok, lambda s: any(e["t"] == "prompt" for e in s))
            self.assertIn("cwd=" + d, "".join(e.get("s", "") for e in seen if e["t"] == "out"))
            self.assertEqual(os.path.realpath(seen[-1]["cwd"]), d)
            r.close(); c.close()
        finally:
            p.kill(); p.wait(); p.stdout.close()

    def test_no_shell_keeps_old_behaviour(self):
        p, port, tok = self.start("--no-shell")
        try:
            seen, r, c = self.read_events(port, tok, lambda s: ">>> " in "".join(e.get("s", "") for e in s if e["t"] == "out"))
            self.assertFalse(any(e["t"] == "prompt" for e in seen))
            r.close(); c.close()
        finally:
            p.kill(); p.wait(); p.stdout.close()

    def test_register_is_windows_only(self):
        if sys.platform == "win32":
            self.skipTest("would touch the real registry")
        r = subprocess.run([sys.executable, "-m", "zagros", "--register"], capture_output=True,
                           text=True, env=env(), timeout=20)
        self.assertEqual(r.returncode, 1)

    def test_end_to_end_no_browser(self):
        d = tempfile.mkdtemp()
        script = os.path.join(d, "hello.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write("print('سلام دنیا')\n")
        p = subprocess.Popen([sys.executable, "-m", "zagros", "--no-browser", script],
                             stdout=subprocess.PIPE, text=True, encoding="utf-8", env=env())
        try:
            line = p.stdout.readline()
            m = re.search(r"http://127\.0\.0\.1:(\d+)/\?t=([\w-]+)", line)
            self.assertIsNotNone(m, line)
            port, tok = int(m.group(1)), m.group(2)
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("GET", f"/events?since=0&t={tok}")
            r = c.getresponse()
            seen = []
            while True:
                ln = r.fp.readline().decode("utf-8")
                if ln.startswith("data: "):
                    seen.append(json.loads(ln[6:]))
                    if seen[-1]["t"] == "exit":
                        break
            self.assertIn("سلام دنیا", "".join(e.get("s", "") for e in seen if e["t"] == "out"))
            r.close(); c.close()            # window closed -> process must exit by itself
            p.wait(timeout=25)
            self.assertEqual(p.returncode, 0)
        finally:
            if p.poll() is None:
                p.kill()
            p.wait()
            p.stdout.close()


if __name__ == "__main__":
    unittest.main()
