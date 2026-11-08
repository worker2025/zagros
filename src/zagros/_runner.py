"""Worker: run a learner's script, then explain any error in Persian.

Executed as a file (``python -u _runner.py script.py [args]``) so zagros is
never placed on the learner's import path.
"""
import importlib.util
import os
import runpy
import sys
import traceback


def _load_doctor():
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "_zagros_doctor", os.path.join(here, "doctor.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    script = os.path.abspath(sys.argv[1])
    doctor = _load_doctor()
    sys.argv = [script] + sys.argv[2:]
    sys.path[0] = os.path.dirname(script)  # same as `python script.py`
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        code = e.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nبرنامه با Ctrl+C متوقف شد.", file=sys.stderr)
        return 130
    except BaseException as e:  # noqa: BLE001 - we report everything
        if isinstance(e, SyntaxError):
            sys.stderr.write("".join(traceback.format_exception_only(type(e), e)))
        else:
            tb = e.__traceback__
            while tb is not None and os.path.abspath(tb.tb_frame.f_code.co_filename) != script:
                tb = tb.tb_next
            traceback.print_exception(type(e), e, tb if tb is not None else e.__traceback__)
        report = doctor.format_report(e)
        if report:
            sys.stderr.write(report)
        sys.stderr.flush()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
