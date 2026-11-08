import os
import tempfile
import time
import unittest

from zagros import dropfiles as d


def make(path, text="print(1)\n", mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


class LocateTests(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.mt = 1_700_000_000

    def find(self, name, p, roots=None, **kw):
        st = os.stat(p)
        return d.locate(name, st.st_size, st.st_mtime * 1000, roots or [self.root], **kw)

    def test_finds_by_name_size_and_mtime(self):
        p = make(os.path.join(self.root, "a", "b", "سلام.py"), mtime=self.mt)
        make(os.path.join(self.root, "x", "سلام.py"), text="different size!!\n", mtime=self.mt)
        self.assertEqual(self.find("سلام.py", p), [p])

    def test_name_match_is_case_insensitive_and_ignores_directories_in_the_name(self):
        p = make(os.path.join(self.root, "Hello.PY"), mtime=self.mt)
        self.assertEqual(self.find("hello.py", p), [p])
        self.assertEqual(self.find("C:\\fake\\dir\\HELLO.py", p), [p])

    def test_mtime_tolerance(self):
        p = make(os.path.join(self.root, "t.py"), mtime=self.mt)
        size = os.stat(p).st_size
        self.assertEqual(d.locate("t.py", size, (self.mt + 2) * 1000, [self.root]), [p])      # FAT: 2 s
        self.assertEqual(d.locate("t.py", size, (self.mt + 60) * 1000, [self.root]), [])

    def test_depth_limit_and_skipped_folders(self):
        deep = make(os.path.join(self.root, "1", "2", "3", "4", "deep.py"), mtime=self.mt)
        self.assertEqual(self.find("deep.py", deep, depth=3), [])
        self.assertEqual(self.find("deep.py", deep, depth=4), [deep])
        for skipped in ("node_modules", ".git", "venv", "__pycache__"):
            q = make(os.path.join(self.root, skipped, "s.py"), mtime=self.mt)
            self.assertEqual(self.find("s.py", q), [], skipped)

    def test_first_root_with_a_match_wins(self):
        other = os.path.realpath(tempfile.mkdtemp())
        a = make(os.path.join(self.root, "same.py"), mtime=self.mt)
        make(os.path.join(other, "same.py"), mtime=self.mt)
        self.assertEqual(self.find("same.py", a, roots=[other, self.root]), [os.path.join(other, "same.py")])

    def test_budget_stops_the_search(self):
        for i in range(30):
            make(os.path.join(self.root, f"f{i}.txt"))
        p = make(os.path.join(self.root, "zz.py"), mtime=self.mt)
        self.assertEqual(self.find("zz.py", p, max_entries=3), [])      # gave up, did not hang
        t0 = time.monotonic()
        self.find("zz.py", p, budget=0.0)
        self.assertLess(time.monotonic() - t0, 1.0)

    def test_no_match(self):
        self.assertEqual(d.locate("nope.py", 1, 0, [self.root]), [])
        self.assertEqual(d.locate("nope.py", 1, 0, ["/definitely/not/here"]), [])

    def test_default_roots_exist_and_are_unique(self):
        roots = d.default_roots(self.root)
        self.assertEqual(roots[0], self.root)
        self.assertEqual(len(roots), len({os.path.realpath(r) for r in roots}))
        self.assertTrue(all(os.path.isdir(r) for r in roots))


class UploadTests(unittest.TestCase):
    def test_safe_script_name(self):
        ok = d.safe_script_name
        self.assertEqual(ok("سلام.py"), "سلام.py")
        self.assertEqual(ok("C:\\Users\\x\\prog.PYW"), "prog.PYW")
        self.assertEqual(ok("../../etc/evil.py"), "evil.py")                 # path stripped
        self.assertEqual(ok('a<b>c:"d|e?.py'), "a_b_c__d_e_.py")
        for bad in ("x.txt", "x.exe", ".py", "", "con.py", "NUL.py", "a" * 130 + ".py", "x.py.exe"):
            self.assertIsNone(ok(bad), bad)

    def test_save_upload(self):
        folder = os.path.join(tempfile.mkdtemp(), "dropped")
        p = d.save_upload("print('سلام')".encode("utf-8"), "../x.py", folder)
        self.assertEqual(os.path.dirname(p), folder)
        with open(p, encoding="utf-8") as f:
            self.assertEqual(f.read(), "print('سلام')")
        with self.assertRaises(ValueError):
            d.save_upload(b"x", "x.txt", folder)
        with self.assertRaises(ValueError):
            d.save_upload(b"x" * (d.MAX_UPLOAD + 1), "big.py", folder)

    def test_quote_path(self):
        self.assertEqual(d.quote_path("a.py"), "a.py")
        self.assertEqual(d.quote_path("my dir/a b.py"), '"my dir/a b.py"')


if __name__ == "__main__":
    unittest.main()
