import unittest

from zagros import doctor


def caught(fn):
    try:
        fn()
    except BaseException as e:  # noqa: BLE001
        return e
    raise AssertionError("did not raise")


class DoctorTests(unittest.TestCase):
    def test_name_suggestion(self):
        out = doctor.explain(caught(lambda: prnt("x")))  # noqa: F821
        self.assertIn("prnt", out)
        self.assertIn("print", out)

    def test_input_is_str_hint(self):
        out = doctor.explain(caught(lambda: 1 + "a"))
        self.assertIn("input()", out)

    def test_persian_decimal_separator(self):
        out = doctor.explain(caught(lambda: float("۳٫۵")))
        self.assertIn("٫", out)

    def test_persian_punctuation_in_code(self):
        e = caught(lambda: compile("a = 1،2", "f", "exec"))
        self.assertIn("فارسی", doctor.explain(e))

    def test_indentation_before_syntax(self):
        e = caught(lambda: compile("if True:\npass", "f", "exec"))
        self.assertIn("تورفتگی", doctor.explain(e))

    def test_unknown_returns_none(self):
        self.assertIsNone(doctor.explain(caught(lambda: "ab".upper(1, 2))))
        self.assertIsNone(doctor.format_report(ValueError("zzz")))

    def test_format_report_has_header(self):
        self.assertIn("دکتر خطا", doctor.format_report(caught(lambda: 1 / 0)))


if __name__ == "__main__":
    unittest.main()
