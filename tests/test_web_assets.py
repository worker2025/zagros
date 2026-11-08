"""The fake DOM in the JS tests has its own list of ids. These tests make sure the REAL index.html
provides every element console.js looks up (a missing id would crash the page in a browser)."""
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src" / "zagros" / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "console.js").read_text(encoding="utf-8")
CSS = (WEB / "style.css").read_text(encoding="utf-8")


class WebAssetTests(unittest.TestCase):
    def test_every_id_used_by_the_script_exists_in_the_page(self):
        wanted = set(re.findall(r'\$\("([A-Za-z0-9_]+)"\)', JS))
        have = re.findall(r'\bid="([^"]+)"', HTML)
        self.assertEqual(len(have), len(set(have)), "duplicate ids in index.html")
        self.assertFalse(wanted - set(have), f"console.js needs ids missing from index.html: {wanted - set(have)}")
        self.assertGreater(len(wanted), 30)

    def test_preset_and_snap_buttons(self):
        self.assertEqual(set(re.findall(r'data-preset="(\w+)"', HTML)), {"small", "medium", "large"})
        self.assertEqual(set(re.findall(r'data-snap="(\w+)"', HTML)), {"left", "center", "right"})

    def test_elements_that_start_hidden_are_hidden_in_markup(self):
        for i in ("btnTop", "btnWin", "popWin", "popSet", "empty", "toBottom", "toast", "drop", "winNote"):
            self.assertRegex(HTML, rf'id="{i}"[^>]*\bhidden\b', i)

    def test_scroll_container_is_not_inside_something_that_clips_it(self):
        self.assertRegex(CSS, r"#screen\s*{[^}]*overflow-y:\s*auto")
        self.assertIn("#screen::-webkit-scrollbar", CSS)                     # a visible, styled scrollbar
        self.assertRegex(CSS, r"\[hidden\]\s*{\s*display:\s*none\s*!important")  # hidden must beat display:flex

    def test_no_status_bar_and_no_inline_code(self):
        self.assertNotIn('id="status"', HTML)
        self.assertNotIn("<footer", HTML)
        self.assertNotIn(" style=", HTML)
        self.assertNotRegex(HTML, r"<script(?![^>]*\bsrc=)")

    def test_credit_is_tiny_and_in_the_settings_panel_only(self):
        self.assertEqual(HTML.count("tirotir.com"), 2)                       # link target + label
        self.assertRegex(HTML, r'<p class="about">.*tirotir\.com.*</p>')
        self.assertIn('rel="noopener noreferrer"', HTML)
        self.assertRegex(CSS, r"\.about\s*{[^}]*font-size:\s*10\.5px")

    def test_result_mode_hides_chatter_and_the_toolbar_extras(self):
        self.assertRegex(CSS, r"body\.result \.meta[^{]*{[^}]*display:\s*none")
        self.assertIn(".shellonly", CSS)
        self.assertRegex(CSS, r"body\.result #screen\s*{[^}]*var\(--rfs")

    def test_script_never_calls_array_methods_on_html_collections(self):
        # `children` is an HTMLCollection in a real browser: it has no .some/.filter/.map/.forEach
        self.assertNotRegex(JS, r"\.children\.(some|filter|map|forEach|find|reduce)\(")
        self.assertNotRegex(JS, r"querySelectorAll\([^)]*\)\.(some|filter|map|forEach)\(")


if __name__ == "__main__":
    unittest.main()
