import os
import tempfile
import threading
import time
import unittest

from zagros.watch import Watcher


def bump(path, text):
    """Rewrite and push mtime forward so the change is visible even on coarse clocks."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    st = os.stat(path)
    os.utime(path, (st.st_atime, st.st_mtime + 5))


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "w.py")
        with open(self.path, "w") as f:
            f.write("print(1)\n")
        self.hits = []
        self.w = Watcher(self.hits.append, interval=0.05, settle=0.05)

    def tearDown(self):
        self.w.stop()

    def wait(self, n, t=5):
        end = time.time() + t
        while len(self.hits) < n and time.time() < end:
            time.sleep(0.02)

    def test_fires_once_per_save_and_not_without_change(self):
        self.w.start(self.path)
        self.assertTrue(self.w.active)
        time.sleep(0.3)
        self.assertEqual(self.hits, [])                      # nothing changed yet
        bump(self.path, "print(2)\n")
        self.wait(1)
        time.sleep(0.3)
        self.assertEqual(self.hits, [self.path])             # exactly once
        bump(self.path, "print(3)\n")
        self.wait(2)
        self.assertEqual(len(self.hits), 2)

    def test_missing_file_during_save_is_ignored(self):
        self.w.start(self.path)
        os.remove(self.path)                                  # editors do this briefly
        time.sleep(0.3)
        self.assertEqual(self.hits, [])
        bump(self.path, "print('back')\n")
        self.wait(1)
        self.assertEqual(len(self.hits), 1)

    def test_stop(self):
        self.w.start(self.path)
        self.w.stop()
        self.assertFalse(self.w.active)
        bump(self.path, "x = 1\n")
        time.sleep(0.3)
        self.assertEqual(self.hits, [])

    def test_callback_errors_do_not_kill_the_watcher(self):
        calls = []

        def boom(p):
            calls.append(p)
            raise RuntimeError("x")

        w = Watcher(boom, interval=0.05, settle=0.05)
        try:
            w.start(self.path)
            bump(self.path, "a = 1\n")
            end = time.time() + 5
            while not calls and time.time() < end:
                time.sleep(0.02)
            bump(self.path, "a = 2\n")
            end = time.time() + 5
            while len(calls) < 2 and time.time() < end:
                time.sleep(0.02)
            self.assertEqual(len(calls), 2)
        finally:
            w.stop()

    def test_restart_replaces_old_loop(self):
        self.w.start(self.path)
        other = os.path.join(os.path.dirname(self.path), "o.py")
        with open(other, "w") as f:
            f.write("1\n")
        self.w.start(other)
        bump(self.path, "changed\n")                          # old file: must not fire
        time.sleep(0.3)
        self.assertEqual(self.hits, [])
        self.assertEqual(threading.active_count() >= 1, True)


if __name__ == "__main__":
    unittest.main()
