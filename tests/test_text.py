import unittest

from zagros import text as t


class TextTests(unittest.TestCase):
    def test_digits(self):
        self.assertEqual(t.to_ascii_digits("۱۲۳ و ٤٥٦"), "123 و 456")
        self.assertEqual(t.to_persian_digits("a12 ٣"), "a۱۲ ۳")

    def test_normalize_input_is_conservative(self):
        self.assertEqual(t.normalize_input("۱۲٫۵"), "12.5")
        self.assertEqual(t.normalize_input("سلام ۳"), "سلام 3")
        self.assertEqual(t.normalize_input("متن ٫ جدا"), "متن ٫ جدا")  # not between digits
        self.assertEqual(t.normalize_input("۱٬۲۳۴"), "1٬234")          # thousands untouched

    def test_parse(self):
        self.assertEqual(t.parse_float("۳٫۵"), 3.5)
        self.assertEqual(t.parse_int("۱٬۲۳۴"), 1234)
        self.assertEqual(t.parse_int(" ۱۲ "), 12)
        with self.assertRaises(ValueError):
            t.parse_int("abc")

    def test_normalize_persian(self):
        self.assertEqual(t.normalize_persian("كتاب يك"), "کتاب یک")
        self.assertEqual(t.normalize_persian("سلــام"), "سلام")

    def test_has_rtl(self):
        self.assertTrue(t.has_rtl("abc سلام"))
        self.assertFalse(t.has_rtl("hello 123"))


if __name__ == "__main__":
    unittest.main()
