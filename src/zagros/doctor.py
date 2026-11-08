"""دکتر خطا: Persian explanations for common Python errors.

Standalone on purpose (stdlib only, no package-relative imports) so the worker
processes can load it by file path without putting zagros on the learner's
``sys.path``.
"""
from __future__ import annotations

import ast
import builtins
import difflib
import keyword
import os
import re

_TYPE_FA = {
    "int": "عدد صحیح", "float": "عدد اعشاری", "str": "متن", "list": "لیست",
    "dict": "دیکشنری", "tuple": "تاپل", "set": "مجموعه", "bool": "بولی",
    "NoneType": "None", "complex": "عدد مختلط", "bytes": "بایت",
}


def _t(name: str) -> str:
    """Persian name of a type, keeping the Python name for clarity."""
    return f"{_TYPE_FA[name]} ({name})" if name in _TYPE_FA else f"«{name}»"


def _suggest(word: str, extra=()) -> str | None:
    pool = list(dir(builtins)) + list(keyword.kwlist) + list(extra)
    hit = difflib.get_close_matches(word, pool, n=1, cutoff=0.7)
    return hit[0] if hit else None


# ---------------------------------------------------------------- syntax ---
def _indentation(e):
    m = e.msg or ""
    if "expected an indented block" in m:
        return ("بعد از خطی که با «:» تمام می‌شود، خط بعدی باید تورفتگی داشته باشد "
                "(معمولاً ۴ فاصله).")
    if "unindent does not match" in m:
        return "تورفتگی این خط با خط‌های بالاتر هم‌تراز نیست؛ تعداد فاصله‌ها را یکی کنید."
    if "unexpected indent" in m:
        return "این خط بی‌دلیل تورفتگی دارد؛ فاصله‌ی ابتدای خط را پاک کنید."
    if isinstance(e, TabError):
        return "در این فایل هم Tab و هم فاصله برای تورفتگی به کار رفته؛ فقط یکی را استفاده کنید."
    return "تورفتگی خط‌ها درست نیست؛ تورفتگی‌ها را بررسی کنید."


def _syntax(e):
    m = e.msg or ""
    if "invalid character" in m or "invalid non-printable" in m:
        return ("در کد نویسه‌ای غیرمجاز هست. معمولاً علامت‌های فارسی مثل «،» «؛» «؟» یا "
                "گیومه‌ی هوشمند را به جای , ; ? \" انگلیسی تایپ کرده‌اید، یا فاصله‌ی ناپیدا "
                "همراه متن کپی شده. زبان صفحه‌کلید را برای کد انگلیسی بگذارید.")
    if "Missing parentheses in call to 'print'" in m:
        return "در پایتون ۳ باید print را با پرانتز بنویسید: print(...)."
    if "expected ':'" in m:
        return "بعد از if، elif، else، for، while، def و class باید «:» بگذارید."
    if "was never closed" in m:
        return "یک پرانتز یا کروشه یا آکولاد را باز کرده‌اید ولی نبسته‌اید."
    if "unmatched" in m:
        return "یک پرانتز یا کروشه یا آکولاد بسته اضافه است و جفتی ندارد."
    if "unterminated string literal" in m or "unterminated triple-quoted" in m:
        return "یک متن را با گیومه شروع کرده‌اید ولی با همان گیومه نبسته‌اید."
    if "Maybe you meant '=='" in m:
        return "برای مقایسه در شرط باید «==» بنویسید؛ «=» برای مقداردهی است."
    if "cannot assign to" in m:
        return "در سمت چپ «=» فقط نام متغیر می‌تواند باشد، نه یک عبارت یا مقدار ثابت."
    return ("ساختار این خط با قواعد پایتون جور نیست. معمولاً دونقطه، پرانتز یا گیومه جا افتاده "
            "یا کلمه‌ای اشتباه نوشته شده. خط قبل را هم نگاه کنید؛ گاهی اشکال از آنجاست.")


# ----------------------------------------------------------------- names ---
def _unbound(e):
    return ("از متغیری استفاده کرده‌اید که داخل تابع مقدار ندارد. یا قبل از مقداردهی خوانده شده "
            "یا می‌خواستید متغیر بیرون از تابع را تغییر دهید که برای آن باید global لازم باشد.")


def _name(e):
    name = getattr(e, "name", None)
    if not name:
        m = re.search(r"name '(.+?)' is not defined", str(e))
        name = m.group(1) if m else None
    if not name:
        return None
    msg = (f"نام «{name}» تعریف نشده است. یا املایش را اشتباه نوشته‌اید، یا قبل از "
           "تعریف از آن استفاده کرده‌اید. به حروف بزرگ و کوچک هم دقت کنید.")
    s = _suggest(name)
    if s:
        msg += f" منظورتان «{s}» بود؟"
    return msg


# ----------------------------------------------------------------- types ---
def _type(e):
    m = str(e)
    r = re.search(r"unsupported operand type\(s\) for (.+?): '(\w+)' and '(\w+)'", m)
    if r:
        op, a, b = r.groups()
        extra = ""
        if "str" in (a, b):
            extra = " ورودی input() همیشه متن است؛ با int() یا float() به عدد تبدیلش کنید."
        return f"عملگر «{op}» بین {_t(a)} و {_t(b)} تعریف نشده است.{extra}"
    r = re.search(r'can only concatenate (\w+) \(not "(\w+)"\) to (\w+)', m)
    if r:
        return ("نمی‌شود متن را با «+» به چیز دیگری چسباند. عدد را با str() به متن تبدیل کنید "
                "یا از f-string استفاده کنید، مثل f\"سن: {age}\".")
    r = re.search(r"'(<|>|<=|>=)' not supported between instances of '(\w+)' and '(\w+)'", m)
    if r:
        _, a, b = r.groups()
        return (f"نمی‌شود {_t(a)} را با {_t(b)} مقایسه کرد. یادتان باشد خروجی input() "
                "همیشه متن است؛ پیش از مقایسه با int() یا float() به عدد تبدیلش کنید.")
    r = re.search(r"'(\w+)' object is not callable", m)
    if r:
        return (f"با پرانتز چیزی را صدا زده‌اید که تابع نیست (از نوع {_t(r.group(1))}). "
                "شاید اسم یک متغیر را هم‌نام یک تابع گذاشته‌اید، مثلاً sum = 0 یا list = [].")
    r = re.search(r"'(\w+)' object is not subscriptable", m)
    if r:
        return f"با [ ] نمی‌شود به درون {_t(r.group(1))} دسترسی گرفت. نوع مقدار را بررسی کنید."
    r = re.search(r"'(\w+)' object is not iterable", m)
    if r:
        return (f"نمی‌شود روی {_t(r.group(1))} حلقه زد. حلقه فقط روی چیزهایی مثل لیست، متن "
                "و range کار می‌کند؛ برای عدد از range(عدد) استفاده کنید.")
    if "does not support item assignment" in m:
        return "این نوع داده را نمی‌شود با اندیس تغییر داد (مثلاً متن و تاپل تغییرناپذیرند)."
    r = re.search(r"takes (\d+) positional arguments? but (\d+) (?:was|were) given", m)
    if r:
        return f"این تابع {r.group(1)} آرگومان می‌خواهد ولی {r.group(2)} تا به آن داده‌اید."
    r = re.search(r"missing (\d+) required positional arguments?: (.+)", m)
    if r:
        return f"آرگومان‌های لازم را نداده‌اید: {r.group(2)}."
    r = re.search(r"object of type '(\w+)' has no len\(\)", m)
    if r:
        return f"len() روی {_t(r.group(1))} کار نمی‌کند؛ فقط برای متن، لیست و مانند آن‌هاست."
    return None


# ---------------------------------------------------------------- values ---
def _value(e):
    m = str(e)
    r = re.search(r"invalid literal for int\(\) with base 10: (.+)$", m)
    if r:
        try:
            v = ast.literal_eval(r.group(1))
        except Exception:
            v = r.group(1)
        if v == "":
            return "ورودی خالی بود و نمی‌شود آن را به عدد تبدیل کرد."
        if "." in v or "\u066b" in v:
            return (f"«{v}» اعشاری است و int() آن را نمی‌پذیرد. اگر اعشار می‌خواهید float() "
                    "به کار ببرید.")
        return (f"نمی‌شود «{v}» را به عدد صحیح تبدیل کرد؛ متن باید فقط ارقام باشد "
                "(بدون حروف، فاصله یا علامت اضافه).")
    r = re.search(r"could not convert string to float: (.+)$", m)
    if r:
        try:
            v = ast.literal_eval(r.group(1))
        except Exception:
            v = r.group(1)
        if "\u066b" in v or "\u066c" in v:
            return ("در عدد از «٫» یا «٬» فارسی استفاده شده؛ پایتون فقط نقطه «.» را برای اعشار "
                    "می‌شناسد. در zagros می‌توانید از parse_float استفاده کنید.")
        if v == "":
            return "ورودی خالی بود و نمی‌شود آن را به عدد تبدیل کرد."
        return f"نمی‌شود «{v}» را به عدد اعشاری تبدیل کرد؛ متن باید شبیه 3.14 باشد."
    if "too many values to unpack" in m or "not enough values to unpack" in m:
        return "تعداد متغیرهای سمت چپ با تعداد مقدارهای سمت راست برابر نیست."
    if "math domain error" in m:
        return "ورودی تابع ریاضی خارج از دامنه‌ی مجاز است (مثلاً جذر یا لگاریتم عدد منفی)."
    return None


def _unicode(e):
    if isinstance(e, UnicodeDecodeError):
        return ("خواندن فایل با رمزگذاری اشتباه انجام شد. برای فایل‌های فارسی هنگام open "
                "بنویسید encoding=\"utf-8\".")
    return ("این نویسه‌ها با رمزگذاری فعلی قابل نوشتن نیستند. هنگام open بنویسید "
            "encoding=\"utf-8\".")


# ----------------------------------------------------------- collections ---
def _index(e):
    return ("اندیس از اندازه‌ی لیست یا متن بیشتر است. اندیس‌ها از ۰ شروع می‌شوند و آخرین "
            "اندیس معتبر len(x) - 1 است.")


def _key(e):
    key = e.args[0] if e.args else "?"
    return (f"کلید {key!r} در دیکشنری نیست. پیش از استفاده با in بررسی کنید یا از "
            "d.get(کلید) استفاده کنید. به حروف بزرگ و کوچک و فاصله‌ها دقت کنید.")


def _attr(e):
    m = str(e)
    r = re.search(r"'(\w+)' object has no attribute '(\w+)'", m)
    if r:
        typ, attr = r.groups()
        if typ == "NoneType":
            return (f"مقدار None است و «{attr}» ندارد. معمولاً تابعی که صدا زده‌اید چیزی "
                    "برنگردانده (مثلاً x = lst.sort() یا تابعی بدون return).")
        return f"{_t(typ)} صفتی یا متدی به نام «{attr}» ندارد. املای آن را بررسی کنید."
    r = re.search(r"module '(\w+)' has no attribute '(\w+)'", m)
    if r:
        mod, attr = r.groups()
        return (f"ماژول «{mod}» چیزی به نام «{attr}» ندارد. املا را بررسی کنید، یا شاید "
                f"فایلی هم‌نام ماژول (مثل {mod}.py) کنار برنامه‌تان هست.")
    return None


# ----------------------------------------------------------------- files ---
def _notfound(e):
    name = getattr(e, "filename", None)
    where = os.getcwd()
    return (f"فایل یا پوشه‌ای به نام {name!r} پیدا نشد. نام و مسیر را بررسی کنید؛ "
            f"برنامه در پوشه‌ی «{where}» اجرا می‌شود و مسیرهای نسبی از همین‌جا شروع می‌شوند.")


def _perm(e):
    return ("اجازه‌ی دسترسی به این فایل را ندارید یا فایل در برنامه‌ی دیگری باز است. "
            "اگر مسیر پوشه است، باید نام فایل را هم بنویسید.")


def _modnotfound(e):
    name = getattr(e, "name", None) or "?"
    top = name.split(".")[0]
    return (f"ماژول «{name}» پیدا نشد. اگر کتابخانه‌ی بیرونی است، در خط فرمان بنویسید: "
            f"pip install {top}. اگر نامش را درست نوشته‌اید، مطمئن شوید همان پایتونی که برنامه "
            "را اجرا می‌کند، کتابخانه را نصب دارد.")


def _import(e):
    return ("نامی که می‌خواهید import کنید در آن ماژول نیست. املا را بررسی کنید، و اگر فایل "
            "خودتان است مطمئن شوید دو فایل همدیگر را دوطرفه import نکرده‌اند.")


def _eof(e):
    return "برنامه منتظر ورودی بود (input) ولی ورودی تمام شد."


def _zero(e):
    return "تقسیم بر صفر ممکن نیست. پیش از تقسیم بررسی کنید مخرج صفر نباشد."


def _recursion(e):
    return ("تابع بی‌پایان خودش را صدا می‌زند. شرط توقف (حالت پایه) بگذارید و مطمئن شوید "
            "هر بار به آن نزدیک‌تر می‌شوید.")


def _tcl(e):
    if "application has been destroyed" in str(e) or "bad window path" in str(e):
        return "از پنجره یا ویجتی استفاده می‌کنید که قبلاً بسته (destroy) شده است."
    return None


_HANDLERS = (
    (IndentationError, _indentation),
    (SyntaxError, _syntax),
    (UnboundLocalError, _unbound),
    (NameError, _name),
    (UnicodeError, _unicode),
    (ZeroDivisionError, _zero),
    (RecursionError, _recursion),
    (TypeError, _type),
    (ValueError, _value),
    (IndexError, _index),
    (KeyError, _key),
    (AttributeError, _attr),
    (FileNotFoundError, _notfound),
    (PermissionError, _perm),
    (IsADirectoryError, _perm),
    (ModuleNotFoundError, _modnotfound),
    (ImportError, _import),
    (EOFError, _eof),
)


def explain(exc: BaseException) -> str | None:
    """Return a Persian explanation for ``exc`` or ``None`` if unknown."""
    for typ, fn in _HANDLERS:
        if isinstance(exc, typ):
            try:
                out = fn(exc)
            except Exception:
                out = None
            if out:
                return out
    if type(exc).__name__ == "TclError":
        return _tcl(exc)
    return None


def format_report(exc: BaseException) -> str | None:
    text = explain(exc)
    return None if text is None else "\n── دکتر خطا ──\n" + text + "\n"
