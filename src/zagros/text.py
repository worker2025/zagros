"""Persian text helpers. Standard library only, no side effects."""
from __future__ import annotations

import re

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
ASCII_DIGITS = "0123456789"

DECIMAL_SEP = "\u066b"    # ٫  Arabic decimal separator (used on Persian keyboards)
THOUSANDS_SEP = "\u066c"  # ٬  Arabic thousands separator

_TO_ASCII = str.maketrans(PERSIAN_DIGITS + ARABIC_DIGITS, ASCII_DIGITS * 2)
_TO_PERSIAN = str.maketrans(ASCII_DIGITS + ARABIC_DIGITS, PERSIAN_DIGITS * 2)
_DEC_BETWEEN_DIGITS = re.compile(r"(?<=[0-9])\u066b(?=[0-9])")
_NORMALIZE = str.maketrans({
    "\u064a": "\u06cc",  # ي -> ی
    "\u0649": "\u06cc",  # ى -> ی
    "\u0643": "\u06a9",  # ك -> ک
})
_RTL_RANGES = ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
               (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))


def to_ascii_digits(s: str) -> str:
    """۱۲۳ and ١٢٣ -> 123."""
    return s.translate(_TO_ASCII)


def to_persian_digits(s: str) -> str:
    """123 and ١٢٣ -> ۱۲۳."""
    return s.translate(_TO_PERSIAN)


def normalize_input(s: str) -> str:
    """Conservative clean-up for what a learner types into ``input()``.

    Converts Persian/Arabic digits to ASCII and a ``٫`` that sits between two
    digits to ``.``. Everything else is left untouched, so ordinary text is safe.
    """
    return _DEC_BETWEEN_DIGITS.sub(".", to_ascii_digits(s))


def _clean_number(s: str) -> str:
    s = to_ascii_digits(s.strip())
    for ch in (THOUSANDS_SEP, ",", " ", "\u00a0", "\u200c", "\u200f", "\u200e"):
        s = s.replace(ch, "")
    return s.replace(DECIMAL_SEP, ".").replace("\u2212", "-")


def parse_float(s: str) -> float:
    """float() that understands Persian digits, ``٫`` and ``٬``."""
    return float(_clean_number(s))


def parse_int(s: str) -> int:
    """int() that understands Persian digits and ``٬``."""
    return int(_clean_number(s))


def normalize_persian(s: str, *, tatweel: bool = True) -> str:
    """Map Arabic letter variants (ي ك ى) to Persian ones; drop tatweel."""
    s = s.translate(_NORMALIZE)
    return s.replace("\u0640", "") if tatweel else s


def has_rtl(s: str) -> bool:
    """True if ``s`` contains any Arabic-script character."""
    for ch in s:
        o = ord(ch)
        for lo, hi in _RTL_RANGES:
            if lo <= o <= hi:
                return True
    return False
