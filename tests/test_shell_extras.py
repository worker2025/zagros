import os
import tempfile
import time
import unittest

from tests.test_shell import ShellCase, write
from tests.test_winctl import MARK, FakeApi
from zagros.examples import EXAMPLES, TEMPLATE
from zagros.session import Session
from zagros.settings import Settings
from zagros.shell import Shell
from zagros.winctl import WindowController


class Extras(ShellCase):
    def setUp(self):
        super().setUp()
        self.settings = Settings(os.path.join(self.tmp, ".settings.json"))
        self.api = FakeApi()
        self.api.add(1, "x " + MARK)
        self.wc = WindowController(MARK, self.api, self.settings)
        self.sh = Shell(self.sess, self.tmp, history_path=self.hist, on_quit=lambda: None,
                        opener=self.opened.append, winctl=self.wc, settings=self.settings)

    def tearDown(self):
        self.sh.close()
        self.wc.stop()
        super().tearDown()

    def events_of(self, kind):
        return [e for e in self.log if e["t"] == kind]


class HelpAndLtrTests(Extras):
    def test_help_mentions_everything_and_credits_tirotir(self):
        text, _ = self.do("help")
        for word in ("tirotir.com", "window", "watch", "new <file>", "examples", "mode result", "zagros"):
            self.assertIn(word, text)

    def test_listings_are_left_to_right_but_help_is_not(self):
        write(os.path.join(self.tmp, "سلام.py"), "")
        _, ev = self.do("ls")
        self.assertTrue(all(e.get("ltr") for e in ev if e["t"] == "out"))
        _, ev = self.do("pwd")
        self.assertTrue(any(e.get("ltr") for e in ev if e["t"] == "out"))
        _, ev = self.do("history")
        self.assertTrue(any(e.get("ltr") for e in ev if e["t"] == "out"))
        _, ev = self.do("help")
        self.assertFalse(any(e.get("ltr") for e in ev))


class RunFileTests(Extras):
    def test_run_file_echoes_the_command_and_changes_folder(self):
        sub = os.path.join(self.tmp, "my dir")
        p = write(os.path.join(sub, "a b.py"), "print('hi')\n")
        self.sh.run_file(p)
        self.wait(lambda lg: lg[-1]["t"] == "prompt")
        out = "".join(e.get("s", "") for e in self.log if e["t"] == "out")
        self.assertIn(f'run "{p}"', out)
        self.assertIn("hi", out)
        self.assertEqual(self.sh.cwd, sub)
        p2 = write(os.path.join(self.tmp, "b.py"), "print('b')\n")
        self.sh.run_file(p2, cd=False)
        self.wait(lambda lg: sum(e["t"] == "prompt" for e in lg) == 2)
        self.assertEqual(self.sh.cwd, sub)


class ExamplesAndNewTests(Extras):
    def test_examples_list_and_creation_never_overwrites(self):
        text, _ = self.do("examples")
        for key in EXAMPLES:
            self.assertIn(key, text)
        self.do("example clock")                                   # waits for the prompt AFTER the run
        with open(os.path.join(self.tmp, "clock.py"), encoding="utf-8") as f:
            self.assertEqual(f.read(), EXAMPLES["clock"][1])
        self.do("نمونه clock")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "clock_2.py")))      # not overwritten
        text, _ = self.do("example nope")
        self.assertIn("نمونه‌ای به نام", text)

    def test_new_creates_opens_runs_and_watches(self):
        self.sh.execute("new برنامه")
        path = os.path.join(self.tmp, "برنامه.py")
        self.wait(lambda lg: any(e["t"] == "out" and "نام شما" in e.get("s", "") for e in lg))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), TEMPLATE)
        self.assertEqual(self.opened, [path])
        self.assertTrue(self.sh.watcher.active)
        self.assertTrue(any(e.get("on") for e in self.events_of("watch")))
        self.sess.stop()                                       # a running program makes the shell refuse input
        self.wait(lambda lg: lg[-1]["t"] == "prompt")
        text, _ = self.do("new برنامه")
        self.assertIn("از قبل", text)                          # never overwrites the learner's file

    def test_new_refuses_existing_file(self):
        write(os.path.join(self.tmp, "have.py"), "x = 1\n")
        text, _ = self.do("new have")
        self.assertIn("از قبل", text)
        self.assertEqual(self.opened, [])
        text, _ = self.do("new")
        self.assertIn("نام فایل", text)


class WatchTests(Extras):
    def setUp(self):
        super().setUp()
        self.p = write(os.path.join(self.tmp, "w.py"), "print('v1')\n")
        self.sh.watcher.interval, self.sh.watcher.settle = 0.05, 0.05

    def bump(self, text):
        with open(self.p, "w", encoding="utf-8") as f:
            f.write(text)
        st = os.stat(self.p)
        os.utime(self.p, (st.st_atime, st.st_mtime + 5))

    def test_watch_file_runs_then_reruns_on_save_and_stops_on_off(self):
        self.do("watch w.py")
        self.assertTrue(self.sh.watcher.active)
        self.bump("print('v2')\n")
        self.wait(lambda lg: sum(e["t"] == "start" for e in lg) == 2)
        self.wait(lambda lg: lg[-1]["t"] == "prompt" and sum(e["t"] == "prompt" for e in lg) >= 2)
        out = "".join(e.get("s", "") for e in self.log if e["t"] == "out")
        self.assertIn("v1", out)
        self.assertIn("v2", out)
        self.assertIn("ذخیره شد", out)
        text, _ = self.do("watch off")
        self.assertFalse(self.sh.watcher.active)
        self.assertTrue(any(e.get("on") is False for e in self.events_of("watch")))
        n = sum(e["t"] == "start" for e in self.log)
        self.bump("print('v3')\n")
        time.sleep(0.4)
        self.pump(0.2)
        self.assertEqual(sum(e["t"] == "start" for e in self.log), n)      # no more automatic runs

    def test_watch_toggle_without_args_and_without_script(self):
        text, _ = self.do("watch")
        self.assertIn("ابتدا", text)
        self.do("run w.py")
        text, _ = self.do("watch")
        self.assertTrue(self.sh.watcher.active)
        text, _ = self.do("watch")
        self.assertFalse(self.sh.watcher.active)

    def test_set_watch_api(self):
        self.assertEqual(self.sh.set_watch(True)["error"], "no script")
        mark = len(self.log)
        self.sh.run_file(self.p)
        self.wait(lambda lg: any(e["t"] == "prompt" for e in lg[mark:]))
        self.assertEqual(self.sh.set_watch(True)["active"], True)
        self.assertEqual(self.sh.set_watch(False)["active"], False)


class ModeTests(Extras):
    def test_mode_result_and_normal_update_settings_and_notify_the_ui(self):
        text, _ = self.do("mode result")
        self.assertTrue(self.settings.get()["resultMode"])
        self.assertTrue(self.events_of("settings")[-1]["settings"]["resultMode"])
        text, _ = self.do("حالت عادی")
        self.assertFalse(self.settings.get()["resultMode"])
        text, _ = self.do("mode banana")
        self.assertIn("استفاده", text)

    def test_mode_without_settings(self):
        sh = Shell(Session(), self.tmp, history_path=self.hist)
        sh.s.write = lambda *a, **k: None
        self.assertFalse(sh._cmd_mode(["result"]))


class WindowCommandTests(Extras):
    def vis(self):
        return self.api.get_visible_rect(1)

    def test_commands_drive_the_controller_and_notify_the_ui(self):
        text, _ = self.do("window top")
        self.assertTrue(self.api.win[1]["ex"] & 0x8)
        self.assertIn("همیشه بالا: بله", text)
        self.do("window top off")
        self.assertFalse(self.api.win[1]["ex"] & 0x8)
        self.do("پنجره بالا")                                     # Persian + toggle
        self.assertTrue(self.api.win[1]["ex"] & 0x8)
        self.do("window size 900x640")
        self.assertEqual((self.vis().width, self.vis().height), (900, 640))
        self.do("window size small")
        self.assertEqual((self.vis().width, self.vis().height), (700, 450))
        self.do("window snap left")
        self.assertEqual((self.vis().left, self.vis().width), (0, 960))
        self.do("پنجره راست")
        self.assertEqual(self.vis().right, 1920)
        self.do("window lock")
        self.assertTrue(self.wc.state()["locked"])
        self.do("window lock off")
        self.assertFalse(self.wc.state()["locked"])
        text, _ = self.do("window opacity 80")
        self.assertIn("شفافیت: 80", text)
        self.assertGreaterEqual(len(self.events_of("window")), 8)
        text, _ = self.do("window")
        self.assertIn("پنجره:", text)

    def test_bad_usage_and_unavailable(self):
        for line in ("window size banana", "window opacity", "window snap up", "window wat"):
            text, _ = self.do(line)
            self.assertIn("استفاده", text, line)
        self.sh.winctl = WindowController(MARK, api=None)
        text, _ = self.do("window top")
        self.assertIn("فقط در ویندوز", text)

    def test_window_not_found(self):
        self.api.win.pop(1)
        text, _ = self.do("window top")
        self.assertIn("انجام نشد", text)


class ExampleProgramsRun(unittest.TestCase):
    """Every built-in example must really run to completion with its sample input."""

    def test_all_examples(self):
        d = tempfile.mkdtemp()
        for key, (_title, src, inputs) in EXAMPLES.items():
            with self.subTest(example=key):
                p = write(os.path.join(d, key + ".py"), src)
                s = Session()
                s.start_script(p)
                time.sleep(0.5)
                for line in inputs:
                    s.send_input(line + "\n")
                    time.sleep(0.1)
                code, last, end, out = None, 0, time.time() + 10, ""
                while code is None and time.time() < end:
                    for i, e in s.events_since(last, 0.5):
                        last = i
                        out += e.get("s", "")
                        if e["t"] == "exit":
                            code = e["code"]
                s.stop()
                self.assertEqual(code, 0, out)
                self.assertNotIn("Traceback", out)
        # the one with arithmetic must not print float noise
        p = write(os.path.join(d, "t2.py"), EXAMPLES["temp"][1])
        s = Session()
        s.start_script(p)
        time.sleep(0.5)
        s.send_input("36.6\n")
        time.sleep(0.8)
        out = "".join(e.get("s", "") for _, e in s.events_since(0, 0.2))
        s.stop()
        self.assertIn("97.9", out)


if __name__ == "__main__":
    unittest.main()
