import os
import tempfile
import textwrap
import time
import unittest

from zagros.session import Session


def collect(sess, until, timeout=10.0):
    """Gather events until ``until(events)`` is true."""
    got, last, end = [], 0, time.time() + timeout
    while time.time() < end:
        for i, e in sess.events_since(last, 0.5):
            last = i
            got.append(e)
        if until(got):
            return got
    raise AssertionError("timeout; got %r" % got[-5:])


def joined(evs, kind):
    return "".join(e["s"] for e in evs if e["t"] == kind)


def script(src):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "prog.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(src))
    return p


class SessionTests(unittest.TestCase):
    def tearDown(self):
        getattr(self, "s", Session()).stop()

    def test_persian_roundtrip_and_exit_code(self):
        p = script('''
            name = input("نام: ")
            print("سلام", name)
        ''')
        self.s = s = Session()
        s.start_script(p)
        collect(s, lambda ev: "نام: " in joined(ev, "out"))
        self.assertTrue(s.send_input("علی\n"))
        ev = collect(s, lambda ev: any(e["t"] == "exit" for e in ev))
        self.assertIn("سلام علی", joined(ev, "out").replace("\n", ""))
        self.assertEqual(ev[-1]["code"], 0)

    def test_error_trimmed_and_explained(self):
        p = script('print(int("abc"))\n')
        self.s = s = Session()
        s.start_script(p)
        ev = collect(s, lambda ev: any(e["t"] == "exit" for e in ev))
        err = joined(ev, "err")
        self.assertIn("ValueError", err)
        self.assertNotIn("_runner.py", err)
        self.assertNotIn("runpy", err)
        self.assertIn("دکتر خطا", err)
        self.assertEqual(ev[-1]["code"], 1)

    def test_syntax_error_reported(self):
        p = script("if True\n    pass\n")
        self.s = s = Session()
        s.start_script(p)
        ev = collect(s, lambda ev: any(e["t"] == "exit" for e in ev))
        self.assertIn("SyntaxError", joined(ev, "err"))
        self.assertIn("دکتر خطا", joined(ev, "err"))

    def test_sys_exit_code_and_argv(self):
        p = script("import sys\nprint(sys.argv[1:])\nsys.exit(3)\n")
        self.s = s = Session()
        s.start_script(p, ["a", "b"])
        ev = collect(s, lambda ev: any(e["t"] == "exit" for e in ev))
        self.assertIn("['a', 'b']", joined(ev, "out"))
        self.assertEqual(ev[-1]["code"], 3)

    def test_script_dir_importable_and_zagros_not_leaked(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "helper.py"), "w") as f:
            f.write("X = 41\n")
        p = os.path.join(d, "prog.py")
        with open(p, "w") as f:
            f.write("import helper, sys\nprint(helper.X + 1)\n"
                    "print(any('zagros' in str(m) for m in sys.modules))\n")
        self.s = s = Session()
        s.start_script(p)
        ev = collect(s, lambda ev: any(e["t"] == "exit" for e in ev))
        self.assertEqual(joined(ev, "out").split(), ["42", "False"])

    def test_stop_kills_running_program(self):
        p = script("import time\nprint('go', flush=True)\ntime.sleep(60)\n")
        self.s = s = Session()
        s.start_script(p)
        collect(s, lambda ev: "go" in joined(ev, "out"))
        s.stop()
        ev = collect(s, lambda ev: any(e["t"] == "exit" for e in ev), timeout=5)
        self.assertTrue(ev[-1]["stopped"])
        self.assertFalse(s.running())

    def test_restart_bumps_run_id(self):
        p = script("print('x')\n")
        self.s = s = Session()
        s.start_script(p)
        collect(s, lambda ev: any(e["t"] == "exit" for e in ev))
        s.start_script(p)
        ev = collect(s, lambda ev: sum(e["t"] == "exit" for e in ev) == 2)
        self.assertEqual({e["run"] for e in ev}, {1, 2})

    def test_repl_runs_code_and_explains_errors(self):
        self.s = s = Session()
        s.start_repl()
        collect(s, lambda ev: ">>> " in joined(ev, "out"))
        s.send_input("print(6 * 7)\n")
        collect(s, lambda ev: "42" in joined(ev, "out"))
        s.send_input("prnt(1)\n")
        ev = collect(s, lambda ev: "دکتر خطا" in joined(ev, "err"))
        self.assertIn("print", joined(ev, "err"))
        s.send_input("exit()\n")
        collect(s, lambda ev: any(e["t"] == "exit" for e in ev))

    def test_missing_script(self):
        with self.assertRaises(FileNotFoundError):
            Session().start_script("/nonexistent/zzz.py")

    def test_send_input_when_idle(self):
        self.assertFalse(Session().send_input("x\n"))


if __name__ == "__main__":
    unittest.main()
