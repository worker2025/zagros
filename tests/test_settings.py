import json
import os
import tempfile
import unittest

from zagros.settings import DEFAULTS, Settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "s.json")

    def test_defaults_and_persistence(self):
        s = Settings(self.path)
        self.assertEqual(s.get(), DEFAULTS)
        s.update({"font": 22, "theme": "dark", "faDigits": True})
        again = Settings(self.path)
        self.assertEqual((again.get()["font"], again.get()["theme"], again.get()["faDigits"]), (22, "dark", True))

    def test_validation_clamps_and_ignores_garbage(self):
        s = Settings(self.path)
        s.update({"font": 999, "theme": "pink", "normalize": "yes", "evil": 1, "resultFont": 5})
        d = s.get()
        self.assertEqual(d["font"], 40)                 # clamped
        self.assertEqual(d["theme"], "auto")            # invalid value ignored
        self.assertIs(d["normalize"], True)             # non-bool ignored
        self.assertNotIn("evil", d)
        self.assertEqual(d["resultFont"], 20)           # clamped up
        s.update({"font": True})                        # bool is not an int
        self.assertEqual(s.get()["font"], 40)

    def test_window_block(self):
        s = Settings(self.path)
        s.update({"window": {"topmost": True, "opacity": 0.1, "w": 50, "h": 700, "x": None, "junk": 1}})
        w = s.get()["window"]
        self.assertTrue(w["topmost"])
        self.assertEqual(w["opacity"], 0.3)             # floor
        self.assertEqual(w["w"], 200)                   # min width
        self.assertEqual(w["h"], 700)
        self.assertNotIn("junk", w)
        s.update({"window": {"opacity": 0.75}})         # partial update keeps the rest
        self.assertEqual(s.get()["window"]["h"], 700)

    def test_corrupt_file_falls_back(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        self.assertEqual(Settings(self.path).get(), DEFAULTS)
        with open(self.path, "w") as f:
            json.dump({"font": "big", "theme": "light"}, f)
        d = Settings(self.path).get()
        self.assertEqual((d["font"], d["theme"]), (17, "light"))

    def test_get_returns_a_copy(self):
        s = Settings(self.path)
        s.get()["window"]["w"] = 1
        self.assertIsNone(s.get()["window"]["w"])


if __name__ == "__main__":
    unittest.main()
