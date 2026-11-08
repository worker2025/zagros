"""zagros - Persian-first console for learning Python."""
from .text import (has_rtl, normalize_input, normalize_persian, parse_float,
                   parse_int, to_ascii_digits, to_persian_digits)

__version__ = "0.3.0"
__all__ = ["__version__", "has_rtl", "normalize_input", "normalize_persian",
           "parse_float", "parse_int", "to_ascii_digits", "to_persian_digits"]
