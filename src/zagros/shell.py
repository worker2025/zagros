"""Shell layer: type commands to run files, change folders, install packages, ...

Everything a learner can type goes through :meth:`Shell.execute`. Built-in commands run
in-process; programs (scripts, pip, git, ...) run as child processes through a Session.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import threading
from pathlib import Path

from . import __version__
from .dropfiles import quote_path
from .examples import EXAMPLES, TEMPLATE
from .session import Session, python_exe
from .watch import Watcher

ALIASES = {
    "run": "run", "اجرا": "run",
    "python": "python", "python3": "python", "py": "python",
    "pip": "pip",
    "cd": "cd", "chdir": "cd", "برو": "cd",
    "pwd": "pwd", "مسیر": "pwd",
    "ls": "ls", "dir": "ls", "فهرست": "ls",
    "clear": "clear", "cls": "clear", "پاک": "clear",
    "help": "help", "?": "help", "راهنما": "help",
    "history": "history", "تاریخچه": "history",
    "edit": "edit", "ویرایش": "edit",
    "exit": "exit", "quit": "exit", "خروج": "exit",
    "window": "window", "پنجره": "window",
    "watch": "watch", "مراقبت": "watch",
    "new": "new", "جدید": "new",
    "examples": "examples", "example": "examples", "نمونه": "examples",
    "mode": "mode", "حالت": "mode",
}
_ON = {"on", "1", "روشن", "بله", "true"}
_OFF = {"off", "0", "خاموش", "نه", "false"}
_WIN_WORDS = {"بالا": "top", "اندازه": "size", "قفل": "lock", "شفافیت": "opacity", "چپ": "left",
              "راست": "right", "وسط": "center", "وضعیت": "info", "info": "info"}

DIR, PY, HEAD, OFF, DIM = "\x1b[94m", "\x1b[92m", "\x1b[1;96m", "\x1b[0m", "\x1b[2m"
HISTORY_MAX = 500

HELP = (
    HEAD + "zagros — دستورها" + OFF + "\n"
    "run <file> [args]   — اجرای برنامه (همچنین: اجرا، python، یا فقط نام فایل: hello.py)\n"
    "new <file>          — ساخت برنامه‌ی تازه، باز شدن در ویرایشگر و اجرای خودکار با هر ذخیره | جدید\n"
    "examples | example <name>  — برنامه‌های نمونه برای شروع | نمونه\n"
    "watch [file|off]    — اجرای خودکار برنامه با هر ذخیره‌ی فایل | مراقبت\n"
    "mode result|normal  — حالت نمایش بزرگِ نتیجه (فقط خروجی برنامه) | حالت نتیجه / حالت عادی\n"
    "python | py         — کنسول تعاملی پایتون؛ python -c \"print(1)\" هم کار می‌کند\n"
    "pip ...             — نصب و مدیریت کتابخانه‌ها (مثلاً pip install requests)\n"
    "cd <folder>         — تغییر پوشه (cd .. ، cd ~ ، cd -) | برو\n"
    "ls | dir            — فهرست فایل‌ها (ls -a برای فایل‌های پنهان) | فهرست\n"
    "pwd | edit <file>   — مسیر فعلی | باز کردن فایل در ویرایشگر | مسیر ، ویرایش\n"
    "window top|size|snap|lock|opacity  — همیشه بالا، اندازه، چسباندن به کنار صفحه، قفل، شفافیت | پنجره\n"
    "clear | history | exit — پاک‌کردن ، تاریخچه ، بستن | پاک ، تاریخچه ، خروج\n"
    "هر دستور دیگری مثل ترمینال معمولی اجرا می‌شود (git ، node ، ...).\n"
    "کلیدها: Tab تکمیل ، ↑ ↓ تاریخچه ، Ctrl+C توقف ، Ctrl+L پاک‌کردن ، F5 اجرای دوباره ، Ctrl+چرخ ماوس اندازه‌ی خط\n"
    "فایل را با ماوس روی پنجره رها کنید تا اجرا شود (با Shift: فقط مسیرش درج می‌شود).\n"
    + DIM + f"zagros {__version__} — by tirotir.com" + OFF + "\n"
)


def split_args(line: str, posix: bool | None = None) -> list[str]:
    """shlex split that keeps Windows backslashes intact."""
    if posix is None:
        posix = os.name != "nt"
    parts = shlex.split(line, posix=posix)
    if not posix:
        parts = [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]
    return parts


# ------------------------------------------------------------ completion ---
def _token_start(line: str, cursor: int) -> int:
    in_q, start = False, 0
    for i, ch in enumerate(line[:cursor]):
        if ch == '"':
            in_q = not in_q
        elif ch == " " and not in_q:
            start = i + 1
    return start


def complete(line: str, cursor: int, cwd: str, commands=()) -> dict:
    """Tab completion. Returns {start, end, replacement|None, items}."""
    cursor = max(0, min(cursor, len(line)))
    start = _token_start(line, cursor)
    token = line[start:cursor]
    quoted = token.startswith('"')
    raw = token[1:] if quoted else token
    first = line[:start].strip() == ""
    ci = os.name == "nt"
    seps = "/\\" if os.name == "nt" else "/"
    cut = max(raw.rfind(c) for c in seps)
    dir_part, base = raw[: cut + 1], raw[cut + 1:]
    sep = "\\" if "\\" in dir_part else ("/" if "/" in dir_part else os.sep)

    none = {"start": start, "end": cursor, "replacement": None, "items": []}
    if raw == "~":
        return {"start": start, "end": cursor, "replacement": "~" + sep, "items": []}

    d = os.path.expanduser(dir_part) if dir_part else ""
    folder = d if os.path.isabs(d) else os.path.join(cwd, d)
    try:
        names = os.listdir(folder)
    except OSError:
        names = []

    def starts(n: str, b: str) -> bool:
        return n.lower().startswith(b.lower()) if ci else n.startswith(b)

    show_hidden = base.startswith(".")
    entries = []
    for n in names:
        if not starts(n, base) or (n.startswith(".") and not show_hidden):
            continue
        entries.append((n, os.path.isdir(os.path.join(folder, n))))
    entries.sort(key=lambda e: (not e[1], e[0].lower()))
    cands = [(dir_part + n + (sep if isdir else ""), isdir, n + (sep if isdir else ""))
             for n, isdir in entries]
    if first and not dir_part:
        cmds = sorted({c for c in commands if starts(c, base)})
        cands = [(c, False, c) for c in cmds] + [
            x for x in cands if x[1] or x[2].lower().endswith((".py", ".pyw"))]
    if not cands:
        return none

    def fmt(text: str, isdir: bool, final: bool) -> str:
        if " " in text or quoted:
            return '"' + text + ('"' if final and not isdir else "")
        return text

    if len(cands) == 1:
        text, isdir, _ = cands[0]
        return {"start": start, "end": cursor,
                "replacement": fmt(text, isdir, True) + ("" if isdir else " "), "items": []}
    raws = [c[0] for c in cands]
    n = len(os.path.commonprefix([r.lower() for r in raws] if ci else raws))
    common = raws[0][:n]
    repl = fmt(common, False, False) if len(common) > len(raw) else None
    return {"start": start, "end": cursor, "replacement": repl, "items": [c[2] for c in cands]}


def _open_file(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}   # no noise in the console
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path], **quiet)


class Shell:
    def __init__(self, session: Session, cwd: str | None = None, *, history_path=None,
                 on_quit=None, opener=None, winctl=None, settings=None) -> None:
        self.s = session
        self.cwd = os.path.abspath(cwd or os.getcwd())
        self.prev: str | None = None
        self.on_quit = on_quit
        self.opener = opener or _open_file
        self.winctl, self.settings = winctl, settings
        self.watcher = Watcher(self._on_file_changed)
        self.history: list[str] = []
        env_path = os.environ.get("ZAGROS_HISTORY")
        self.history_path = Path(history_path or env_path or Path.home() / ".zagros_history")
        self._lock = threading.RLock()
        session.shell_mode = True
        session.on_exit = lambda code: self.emit_prompt()
        self._load_history()

    # -- prompt / banner ---------------------------------------------------
    def prompt_text(self) -> str:
        home = os.path.expanduser("~")
        p = self.cwd
        if p == home:
            p = "~"
        elif p.startswith(home.rstrip(os.sep) + os.sep):
            p = "~" + p[len(home.rstrip(os.sep)):]
        return p + "> "

    def emit_prompt(self) -> None:
        self.s.emit(t="prompt", s=self.prompt_text(), cwd=self.cwd)

    def welcome(self, prompt: bool = True) -> None:
        self.s.write(f"{HEAD}zagros{OFF} — کنسول فارسی پایتون\n"
                     "برای راهنما بنویسید: help   |   اجرای فایل: run برنامه.py یا فقط نام فایل\n")
        if prompt:
            self.emit_prompt()

    # -- history -----------------------------------------------------------
    def _load_history(self) -> None:
        try:
            lines = self.history_path.read_text(encoding="utf-8").splitlines()
            self.history = [ln for ln in lines if ln.strip()][-HISTORY_MAX:]
        except OSError:
            self.history = []

    def _remember(self, line: str) -> None:
        if self.history and self.history[-1] == line:
            return
        self.history.append(line)
        del self.history[:-HISTORY_MAX]
        try:
            self.history_path.write_text("\n".join(self.history) + "\n", encoding="utf-8")
        except OSError:
            pass

    # -- completion --------------------------------------------------------
    def complete(self, line: str, cursor: int) -> dict:
        return complete(line, cursor, self.cwd, tuple(ALIASES))

    # -- output helpers ----------------------------------------------------
    def _out(self, text: str, ltr: bool = False) -> None:
        self.s.write(text, ltr=ltr)

    def _err(self, text: str) -> None:
        self.s.write(text, err=True)

    def _resolve(self, p: str) -> str:
        return os.path.normpath(os.path.join(self.cwd, os.path.expanduser(p)))

    # -- dispatch ----------------------------------------------------------
    def execute(self, line: str) -> None:
        with self._lock:
            try:
                started = self._execute(line)
            except OSError as e:
                self._err(f"خطا: {e}\n")
                started = False
            except Exception as e:  # noqa: BLE001
                self._err(f"خطای داخلی: {type(e).__name__}: {e}\n")
                started = False
            if not started:
                self.emit_prompt()

    def _execute(self, line: str) -> bool:
        line = line.strip()
        if not line:
            return False
        self._remember(line)
        if self.s.running():
            self._err("برنامه‌ای در حال اجراست؛ ابتدا آن را متوقف کنید.\n")
            return True  # no new prompt: the running program will produce one
        try:
            argv = split_args(line)
        except ValueError:
            self._err("گیومه بسته نشده است.\n")
            return False
        if not argv:
            return False
        name = ALIASES.get(argv[0].lower())
        if name:
            return getattr(self, "_cmd_" + name)(argv[1:])
        if argv[0].lower().endswith((".py", ".pyw")):
            return self._run_script(argv[0], argv[1:])
        return self._system(line, argv)

    # -- running things ----------------------------------------------------
    def _run_script(self, target: str, args: list[str]) -> bool:
        path = self._resolve(target)
        if not os.path.isfile(path) and not os.path.splitext(path)[1] and os.path.isfile(path + ".py"):
            path += ".py"
        if not os.path.isfile(path):
            self._err(f"فایل پیدا نشد: {target}\n(پوشه‌ی فعلی: {self.cwd}؛ با ls فایل‌ها را ببینید.)\n")
            return False
        self.s.start_script(path, args, cwd=self.cwd)
        return True

    def _system(self, line: str, argv: list[str]) -> bool:
        cmd = f"chcp 65001>nul & {line}" if sys.platform == "win32" else line
        self.s.start_command(cmd, cwd=self.cwd, title=argv[0], shell=True)
        return True

    def _cmd_run(self, args) -> bool:
        if not args:
            self._err("نام فایل را بدهید. مثال: run برنامه.py\n")
            return False
        return self._run_script(args[0], args[1:])

    def _cmd_python(self, args) -> bool:
        if args and re.fullmatch(r"-\d(\.\d+)?", args[0]):  # `py -3`
            args = args[1:]
        if not args:
            self.s.start_repl(self.cwd)
            return True
        if args[0].lower().endswith((".py", ".pyw")):
            return self._run_script(args[0], args[1:])
        self.s.start_command([python_exe(), "-u", *args], cwd=self.cwd, title="python")
        return True

    def _cmd_pip(self, args) -> bool:
        self.s.start_command([python_exe(), "-u", "-m", "pip", *args], cwd=self.cwd, title="pip")
        return True

    # -- built-ins ---------------------------------------------------------
    def _cmd_help(self, args) -> bool:
        self._out(HELP)
        return False

    def _cmd_pwd(self, args) -> bool:
        self._out(self.cwd + "\n", ltr=True)
        return False

    def _cmd_clear(self, args) -> bool:
        self.s.emit(t="clear")
        return False

    def _cmd_history(self, args) -> bool:
        for i, h in enumerate(self.history, 1):
            self._out(f"{i:4}  {h}\n", ltr=True)
        return False

    def _cmd_exit(self, args) -> bool:
        self._out("خداحافظ!\n")
        if self.on_quit:
            self.on_quit()
        return True

    def _cmd_cd(self, args) -> bool:
        if args and args[0].lower() == "/d":
            args = args[1:]
        target = " ".join(args).strip().strip('"')
        if not target:
            self._out(self.cwd + "\n")
            return False
        if target == "-":
            if not self.prev:
                self._err("پوشه‌ی قبلی وجود ندارد.\n")
                return False
            dest = self.prev
        else:
            if len(target) == 2 and target[1] == ":":
                target += os.sep
            dest = self._resolve(target)
        if not os.path.isdir(dest):
            self._err(f"پوشه‌ای با این نام پیدا نشد: {target}\n")
            return False
        self.prev, self.cwd = self.cwd, dest
        return False

    def _cmd_ls(self, args) -> bool:
        hidden, paths = False, []
        for a in args:
            if a.startswith("-"):
                hidden = hidden or "a" in a
            elif os.name == "nt" and a.startswith("/"):
                continue
            else:
                paths.append(a)
        target = self._resolve(" ".join(paths)) if paths else self.cwd
        if os.path.isfile(target):
            self._out(os.path.basename(target) + "\n", ltr=True)
            return False
        try:
            names = os.listdir(target)
        except OSError:
            self._err(f"پوشه‌ای با این نام پیدا نشد: {' '.join(paths)}\n")
            return False
        rows = [(n, os.path.isdir(os.path.join(target, n))) for n in names
                if hidden or not n.startswith(".")]
        rows.sort(key=lambda r: (not r[1], r[0].lower()))
        if not rows:
            self._out("(خالی)\n")
        for n, isdir in rows:
            if isdir:
                self._out(f"{DIR}{n}/{OFF}\n", ltr=True)
            elif n.lower().endswith((".py", ".pyw")):
                self._out(f"{PY}{n}{OFF}\n", ltr=True)
            else:
                self._out(n + "\n", ltr=True)
        return False

    def _cmd_edit(self, args) -> bool:
        if not args:
            self._err("نام فایل را بدهید. مثال: edit برنامه.py\n")
            return False
        path = self._resolve(" ".join(args).strip('"'))
        if not os.path.isfile(path):
            self._err(f"فایل پیدا نشد: {' '.join(args)}\n")
            return False
        try:
            self.opener(path)
        except OSError as e:
            self._err(f"باز نشد: {e}\n")
            return False
        self._out(f"باز شد: {path}\n")
        return False

    # -- running a file for the UI (picker / drop / re-run) ----------------
    def run_file(self, path: str, args=None, cd: bool = True) -> None:
        with self._lock:
            if cd:
                self.cwd = os.path.dirname(os.path.abspath(path))
            self.s.write(f"\x1b[96mrun {quote_path(path)}\x1b[0m\n")   # looks like the typed command
            self.s.start_script(path, list(args or []), cwd=self.cwd)

    # -- settings ----------------------------------------------------------
    def apply_settings(self, patch: dict) -> dict:
        data = self.settings.update(patch)
        self.s.emit(t="settings", settings=data)
        return data

    def _cmd_mode(self, args) -> bool:
        word = (args[0] if args else "").lower()
        if word in ("result", "نتیجه", "big", "بزرگ"):
            on = True
        elif word in ("normal", "عادی", "shell", "off"):
            on = False
        else:
            self._err("استفاده: mode result  یا  mode normal   (فارسی: حالت نتیجه / حالت عادی)\n")
            return False
        if self.settings is None:
            self._err("تنظیمات در دسترس نیست.\n")
            return False
        self.apply_settings({"resultMode": on})
        self._out("حالت نمایش بزرگ " + ("روشن شد؛ برای برگشت دکمه‌ی «نمایش بزرگ» را بزنید." if on else "خاموش شد.") + "\n")
        return False

    # -- watch (re-run on save) -------------------------------------------
    def _on_file_changed(self, path: str) -> None:
        with self._lock:
            self.s.write(f"{DIM}— {os.path.basename(path)} ذخیره شد؛ اجرای دوباره —{OFF}\n")
            try:
                self.s.start_script(path, self.s.last_args, cwd=self.cwd)
            except OSError as e:
                self._err(f"اجرا نشد: {e}\n")

    def set_watch(self, on: bool, path: str | None = None) -> dict:
        path = path or self.s.last_script
        if on:
            if not path:
                return {"ok": False, "error": "no script"}
            self.watcher.start(path)
        else:
            self.watcher.stop()
        self.s.emit(t="watch", on=self.watcher.active, path=self.watcher.path if on else None)
        return {"ok": True, "active": self.watcher.active, "path": path}

    def _cmd_watch(self, args) -> bool:
        word = args[0].lower() if args else ""
        if word in _OFF:
            self.set_watch(False)
            self._out("اجرای خودکار خاموش شد.\n")
            return False
        if args and word not in _ON:
            started = self._run_script(args[0], args[1:])
            if started:
                self.set_watch(True, self.s.last_script)
                self._out(f"اجرای خودکار روشن شد: {os.path.basename(self.s.last_script)} را ذخیره کنید تا دوباره اجرا شود.\n")
            return started
        if not args and self.watcher.active:
            self.set_watch(False)
            self._out("اجرای خودکار خاموش شد.\n")
            return False
        r = self.set_watch(True)
        if not r["ok"]:
            self._err("ابتدا یک برنامه اجرا کنید یا بنویسید: watch برنامه.py\n")
        else:
            self._out(f"اجرای خودکار روشن شد: {os.path.basename(r['path'])}\n")
        return False

    # -- beginner helpers --------------------------------------------------
    def _cmd_new(self, args) -> bool:
        if not args:
            self._err("نام فایل را بدهید. مثال: new برنامه\n")
            return False
        name = " ".join(args).strip('"')
        if not name.lower().endswith((".py", ".pyw")):
            name += ".py"
        path = self._resolve(name)
        if os.path.exists(path):
            self._err(f"این فایل از قبل هست: {name}\n")
            return False
        with open(path, "w", encoding="utf-8") as f:
            f.write(TEMPLATE)
        self._out(f"ساخته شد: {path}\n")
        try:
            self.opener(path)
        except OSError as e:
            self._err(f"در ویرایشگر باز نشد ({e}). خودتان آن را باز کنید.\n")
        self.s.start_script(path, [], cwd=self.cwd)
        self.set_watch(True, path)
        self._out("هر بار فایل را ذخیره کنید، برنامه خودکار دوباره اجرا می‌شود.\n")
        return True

    def _cmd_examples(self, args) -> bool:
        if not args:
            self._out(f"{HEAD}برنامه‌های نمونه{OFF} (برای ساخت و اجرا بنویسید: example نام)\n")
            for key, (title, _src, _inp) in EXAMPLES.items():
                self._out(f"  {key:<8} — {title}\n")
            return False
        key = args[0].lower()
        if key not in EXAMPLES:
            self._err(f"نمونه‌ای به نام {args[0]} نیست. فهرست: examples\n")
            return False
        base, n = key, 1
        path = self._resolve(base + ".py")
        while os.path.exists(path):
            n += 1
            path = self._resolve(f"{base}_{n}.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(EXAMPLES[key][1])
        self._out(f"ساخته شد: {path}\n")
        self.s.start_script(path, [], cwd=self.cwd)
        return True

    # -- window ------------------------------------------------------------
    def _cmd_window(self, args) -> bool:
        wc = self.winctl
        if wc is None or not wc.available():
            self._err("کنترل پنجره فقط در ویندوز و در حالت پنجره‌ی مستقل کار می‌کند.\n")
            return False
        sub = (args[0].lower() if args else "info")
        sub = _WIN_WORDS.get(sub, sub)
        rest = [a.lower() for a in args[1:]]
        st = wc.state()
        body: dict | None = None
        if sub == "info":
            pass
        elif sub == "top":
            body = {"action": "topmost", "on": (rest[0] in _ON) if rest else not st.get("topmost")}
        elif sub == "lock":
            body = {"action": "lock", "on": (rest[0] in _ON) if rest else not st.get("locked")}
        elif sub == "size":
            m = re.fullmatch(r"(\d+)\s*[x×*]\s*(\d+)", " ".join(rest).replace(" ", ""))
            if m:
                body = {"action": "size", "w": int(m[1]), "h": int(m[2])}
            elif rest and rest[0] in ("small", "medium", "large"):
                body = {"action": "preset", "name": rest[0]}
            else:
                self._err("استفاده: window size 900x600   یا   window size small|medium|large\n")
                return False
        elif sub in ("left", "right", "center"):
            body = {"action": "snap", "side": sub}
        elif sub == "snap" and rest and rest[0] in ("left", "right", "center"):
            body = {"action": "snap", "side": rest[0]}
        elif sub == "opacity" and rest and rest[0].isdigit():
            body = {"action": "opacity", "value": int(rest[0]) / 100}
        else:
            self._err("استفاده: window top|lock [on|off] ، size 900x600 ، left|right|center ، opacity 80\n")
            return False
        r = wc.action(body) if body else {"ok": True, **st}
        if not r.get("ok"):
            self._err(f"انجام نشد: {r.get('error')}\n")
            return False
        yes = lambda b: "بله" if b else "خیر"   # noqa: E731
        self._out(f"پنجره: {r.get('w')}×{r.get('h')} ، همیشه بالا: {yes(r.get('topmost'))} ، "
                  f"قفل اندازه: {yes(r.get('locked'))} ، شفافیت: {round(r.get('opacity', 1) * 100)}٪\n")
        self.s.emit(t="window")
        return False

    def close(self) -> None:
        self.watcher.stop()
