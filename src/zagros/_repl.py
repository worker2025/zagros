"""Worker: an interactive Python console with Persian error explanations."""
import code
import importlib.util
import os
import sys


def _load_doctor():
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "_zagros_doctor", os.path.join(here, "doctor.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DOCTOR = _load_doctor()


class FaConsole(code.InteractiveConsole):
    def _doctor(self):
        exc = sys.exc_info()[1]
        report = DOCTOR.format_report(exc) if exc is not None else None
        if report:
            self.write(report)

    def showtraceback(self):
        super().showtraceback()
        self._doctor()

    def showsyntaxerror(self, filename=None, **kwargs):
        super().showsyntaxerror(filename, **kwargs)
        self._doctor()


def main():
    sys.path.insert(0, "")
    sys.ps1, sys.ps2 = ">>> ", "... "
    banner = ("Python %s — کنسول فارسی (zagros)\n"
              "برای خروج بنویسید exit()" % sys.version.split()[0])
    FaConsole(locals={"__name__": "__main__", "__doc__": None}).interact(
        banner=banner, exitmsg="")


if __name__ == "__main__":
    main()
