"""Windows Explorer integration: "اجرا با zagros" in the right-click menu of .py files.

Writes only under HKEY_CURRENT_USER (no admin rights) and only *adds a verb* under
``SystemFileAssociations``; it never changes which program opens ``.py`` files.
``unregister`` removes exactly what ``register`` created.
"""
from __future__ import annotations

import os

from .session import python_exe

EXTS = (".py", ".pyw")
# (registry verb name, menu label, extra command-line flags)
VERBS = (
    ("zagros", "اجرا با zagros", ""),
    ("zagros_result", "نمایش نتیجه با zagros (حالت بزرگ)", "--result "),
)
LABEL = VERBS[0][1]
_KEY = r"Software\Classes\SystemFileAssociations\{ext}\shell\{verb}"


def pythonw() -> str:
    cand = os.path.join(os.path.dirname(python_exe()), "pythonw.exe")
    return cand if os.path.exists(cand) else python_exe()


def command_line(exe: str | None = None, flags: str = "") -> str:
    # --chdir-script: Explorer does not guarantee the working folder, so use the file's folder.
    return f'"{exe or pythonw()}" -m zagros {flags}--chdir-script "%1"'


def entries(exe: str | None = None) -> list[tuple[str, str, str]]:
    """(registry subkey under HKCU, value name ('' = default), value)."""
    out = []
    for ext in EXTS:
        for verb, label, flags in VERBS:
            key = _KEY.format(ext=ext, verb=verb)
            out.append((key, "", label))
            out.append((key + r"\command", "", command_line(exe, flags)))
    return out


def register(winreg=None, exe: str | None = None) -> list[str]:
    if winreg is None:
        import winreg  # Windows only
    done = []
    for key, name, value in entries(exe):
        h = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key)
        try:
            winreg.SetValueEx(h, name, 0, winreg.REG_SZ, value)
        finally:
            winreg.CloseKey(h)
        done.append(key)
    return done


def unregister(winreg=None) -> list[str]:
    if winreg is None:
        import winreg  # Windows only
    removed = []
    for ext in EXTS:
        for verb, _label, _flags in VERBS:
            base = _KEY.format(ext=ext, verb=verb)
            for key in (base + r"\command", base):       # children first
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
                    removed.append(key)
                except FileNotFoundError:
                    pass
    return removed
