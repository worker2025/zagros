import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from zagros.session import Session
from zagros.shell import Shell, complete, split_args

POSIX = os.name != "nt"
CMDS = ("run", "help", "اجرا", "cd", "clear", "history")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(text))
    return path


class ShellCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.sess = Session()
        self.quit, self.opened = [], []
        self.hist = os.path.join(self.tmp, ".hist")
        self.sh = Shell(self.sess, self.tmp, history_path=self.hist,
                        on_quit=lambda: self.quit.append(1), opener=self.opened.append)
        self.log, self.cursor = [], 0

    def tearDown(self):
        self.sess.stop()

    def pump(self, timeout=0.3):
        for i, e in self.sess.events_since(self.cursor, timeout):
            self.cursor = i
            self.log.append(e)

    def wait(self, pred, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            self.pump(0.2)
            if pred(self.log):
                return
        raise AssertionError("timeout; tail=%r" % self.log[-6:])

    def do(self, line):
        """Execute and wait for the next prompt; return (text, events-slice)."""
        mark = len(self.log)
        self.sh.execute(line)
        self.wait(lambda lg: any(e["t"] == "prompt" for e in lg[mark:]))
        ev = self.log[mark:]
        return "".join(e.get("s", "") for e in ev if e["t"] in ("out", "err")), ev


class BuiltinTests(ShellCase):
    def test_help_and_prompt(self):
        text, ev = self.do("help")
        self.assertIn("run <file>", text)
        self.assertEqual(ev[-1]["t"], "prompt")
        self.assertEqual(ev[-1]["cwd"], self.tmp)
        self.assertTrue(ev[-1]["s"].endswith("> "))

    def test_empty_line_reprompts(self):
        _, ev = self.do("   ")
        self.assertEqual([e["t"] for e in ev], ["prompt"])

    def test_cd_with_spaces_persian_and_back(self):
        sub = os.path.join(self.tmp, "پوشه ۱")
        os.mkdir(sub)
        _, ev = self.do("cd پوشه ۱")                # no quotes needed
        self.assertEqual(ev[-1]["cwd"], sub)
        _, ev = self.do("cd ..")
        self.assertEqual(ev[-1]["cwd"], self.tmp)
        _, ev = self.do("cd -")
        self.assertEqual(ev[-1]["cwd"], sub)
        _, ev = self.do("برو ..")                    # Persian alias of cd
        self.assertEqual(ev[-1]["cwd"], self.tmp)

    def test_cd_missing_folder(self):
        text, ev = self.do("cd nope")
        self.assertIn("پیدا نشد", text)
        self.assertEqual(ev[-1]["cwd"], self.tmp)

    def test_pwd(self):
        text, _ = self.do("pwd")
        self.assertEqual(text.strip(), self.tmp)

    def test_ls_order_hidden_and_flags(self):
        write(os.path.join(self.tmp, "a.py"), "")
        write(os.path.join(self.tmp, "b.txt"), "")
        write(os.path.join(self.tmp, ".secret"), "")
        os.mkdir(os.path.join(self.tmp, "zdir"))
        text, _ = self.do("ls")
        plain = text.replace("\x1b[94m", "").replace("\x1b[92m", "").replace("\x1b[0m", "")
        names = [n for n in plain.split("\n") if n and n != ".hist"]
        self.assertEqual(names, ["zdir/", "a.py", "b.txt"])        # dirs first
        self.assertNotIn(".secret", plain)
        text, _ = self.do("ls -a")
        self.assertIn(".secret", text)
        text, _ = self.do("فهرست")
        self.assertIn("a.py", text)

    def test_clear_event(self):
        _, ev = self.do("cls")
        self.assertIn("clear", [e["t"] for e in ev])

    def test_history_persisted_and_deduped(self):
        self.do("pwd"); self.do("pwd"); self.do("help")
        self.assertEqual(self.sh.history, ["pwd", "help"])
        again = Shell(Session(), self.tmp, history_path=self.hist)
        self.assertEqual(again.history, ["pwd", "help"])
        text, _ = self.do("history")
        self.assertIn("pwd", text)

    def test_edit_uses_opener(self):
        p = write(os.path.join(self.tmp, "x.py"), "print(1)\n")
        text, _ = self.do("edit x.py")
        self.assertEqual(self.opened, [p])
        text, _ = self.do("ویرایش nope.py")
        self.assertIn("پیدا نشد", text)

    def test_exit_calls_on_quit(self):
        self.sh.execute("خروج")
        self.assertEqual(self.quit, [1])

    def test_bad_quotes(self):
        text, ev = self.do('run "oops')
        self.assertIn("گیومه", text)

    def test_unknown_run_target(self):
        text, _ = self.do("run nothere.py")
        self.assertIn("پیدا نشد", text)
        text, _ = self.do("nothere.py")
        self.assertIn("پیدا نشد", text)
        text, _ = self.do("run")
        self.assertIn("نام فایل", text)


class RunTests(ShellCase):
    def setUp(self):
        super().setUp()
        write(os.path.join(self.tmp, "hello.py"), 'print("سلام")\n')

    def test_all_ways_to_run_a_file(self):
        lines = ["run hello.py", "run hello", "اجرا hello.py", "hello.py", "python hello.py",
                 "py -3 hello.py", "py hello.py"]
        if POSIX:
            lines.append("./hello.py")
        for line in lines:
            with self.subTest(line=line):
                text, ev = self.do(line)
                self.assertIn("سلام", text)
                self.assertEqual(next(e for e in ev if e["t"] == "exit")["code"], 0)
                self.assertEqual(ev[-1]["t"], "prompt")             # prompt returns afterwards

    def test_arguments_with_quotes(self):
        write(os.path.join(self.tmp, "args.py"), "import sys\nprint(sys.argv[1:])\n")
        text, _ = self.do('run args.py a "b c"')
        self.assertIn("['a', 'b c']", text)

    def test_cwd_is_shell_folder_but_script_dir_is_importable(self):
        write(os.path.join(self.tmp, "sub", "helper.py"), "X = 41\n")
        write(os.path.join(self.tmp, "sub", "prog.py"),
              "import os, helper\nprint(os.getcwd())\nprint(helper.X + 1)\n")
        text, _ = self.do("run sub/prog.py")
        self.assertEqual(text.split(), [self.tmp, "42"])

    def test_script_error_is_explained_then_prompt(self):
        write(os.path.join(self.tmp, "bad.py"), 'print(int("x"))\n')
        text, ev = self.do("run bad.py")
        self.assertIn("دکتر خطا", text)
        self.assertEqual(next(e for e in ev if e["t"] == "exit")["code"], 1)

    def test_python_dash_c_and_repl(self):
        text, _ = self.do('python -c "print(6*7)"')
        self.assertIn("42", text)
        self.sh.execute("python")                       # REPL
        self.wait(lambda lg: ">>> " in "".join(e.get("s", "") for e in lg if e["t"] == "out"))
        self.sess.send_input("exit()\n")
        self.wait(lambda lg: lg[-1]["t"] == "prompt")

    def test_pip(self):
        text, ev = self.do("pip --version")
        self.assertIn("pip", text.lower())

    @unittest.skipUnless(POSIX, "uses the POSIX shell")
    def test_system_commands(self):
        text, _ = self.do("echo سلام دنیا")
        self.assertIn("سلام دنیا", text)
        text, ev = self.do("false")
        self.assertEqual(next(e for e in ev if e["t"] == "exit")["code"], 1)
        text, ev = self.do("definitely-not-a-command-xyz")
        self.assertEqual(next(e for e in ev if e["t"] == "exit")["code"], 127)

    def test_shell_refuses_input_while_program_runs_then_prompts_after_stop(self):
        write(os.path.join(self.tmp, "long.py"), "import time\nprint('go', flush=True)\ntime.sleep(60)\n")
        self.sh.execute("run long.py")
        self.wait(lambda lg: "go" in "".join(e.get("s", "") for e in lg if e["t"] == "out"))
        mark = len(self.log)
        self.sh.execute("pwd")
        self.pump(0.5)
        new = self.log[mark:]
        self.assertTrue(any("در حال اجراست" in e.get("s", "") for e in new))
        self.assertFalse(any(e["t"] == "prompt" for e in new))
        self.sess.stop()                                  # user pressed Stop
        self.wait(lambda lg: lg[-1]["t"] == "prompt")
        self.assertTrue(next(e for e in reversed(self.log) if e["t"] == "exit")["stopped"])

    def test_replacing_a_program_does_not_emit_a_stale_prompt(self):
        write(os.path.join(self.tmp, "long.py"), "import time\nprint('go', flush=True)\ntime.sleep(60)\n")
        self.sh.execute("run long.py")
        self.wait(lambda lg: any(e["t"] == "out" and "go" in e["s"] for e in lg))
        self.sess.start_script(os.path.join(self.tmp, "hello.py"))      # e.g. the Re-run button
        self.wait(lambda lg: lg[-1]["t"] == "prompt")
        kinds = [(e["t"], e["run"]) for e in self.log if e["t"] in ("start", "exit", "prompt")]
        self.assertEqual(kinds, [("start", 1), ("exit", 1), ("start", 2), ("exit", 2), ("prompt", 0)])

    @unittest.skipUnless(POSIX and shutil.which("pgrep"), "needs POSIX + pgrep")
    def test_stop_kills_the_whole_process_tree(self):
        n = 3000 + os.getpid() % 5000          # unique, built at run time (no false matches)
        pat = f"^sleep {n}$"
        alive = lambda: subprocess.run(["pgrep", "-f", pat], capture_output=True).returncode == 0
        self.sh.execute(f'sh -c "sleep {n} & wait"')
        self.wait(lambda lg: any(e["t"] == "start" for e in lg))
        end = time.time() + 5
        while not alive() and time.time() < end:
            time.sleep(0.1)
        self.assertTrue(alive(), "grandchild should be running before Stop")
        self.sess.stop()
        end = time.time() + 5
        while alive() and time.time() < end:
            time.sleep(0.1)
        self.assertFalse(alive(), "Stop must kill the grandchild too")


class SplitTests(unittest.TestCase):
    def test_posix(self):
        self.assertEqual(split_args('run a "b c" d\\ e', posix=True), ["run", "a", "b c", "d e"])

    def test_windows_keeps_backslashes_and_strips_quotes(self):
        self.assertEqual(split_args(r'run C:\proj\x.py "C:\my dir\y.py" z', posix=False),
                         ["run", r"C:\proj\x.py", r"C:\my dir\y.py", "z"])


class CompleteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = os.path.realpath(tempfile.mkdtemp())
        for f in ("alpha.py", "alpha_two.py", "beta.txt", "data.csv", ".hidden", "پروژه.py",
                  "my notes.txt", os.path.join("sub", "inner.py")):
            write(os.path.join(cls.tmp, f), "")
        os.makedirs(os.path.join(cls.tmp, "My Docs"))

    def c(self, line, cursor=None):
        return complete(line, len(line) if cursor is None else cursor, self.tmp, CMDS)

    def test_common_prefix_and_list(self):
        r = self.c("run al")
        self.assertEqual(r["replacement"], "alpha")
        self.assertEqual(r["items"], ["alpha.py", "alpha_two.py"])
        self.assertEqual((r["start"], r["end"]), (4, 6))

    def test_unique_file_gets_trailing_space(self):
        self.assertEqual(self.c("run alpha.")["replacement"], "alpha.py ")

    def test_commands_and_persian_commands(self):
        self.assertEqual(self.c("he")["replacement"], "help ")
        self.assertEqual(self.c("اج")["replacement"], "اجرا ")

    def test_first_token_offers_only_python_files_and_dirs(self):
        r = self.c("")
        self.assertIn("alpha.py", r["items"])
        self.assertNotIn("beta.txt", r["items"])
        self.assertIn("sub/", r["items"] if POSIX else [i.replace("\\", "/") for i in r["items"]])

    def test_persian_filename(self):
        self.assertEqual(self.c("run پر")["replacement"], "پروژه.py ")

    def test_names_with_spaces_are_quoted(self):
        self.assertEqual(self.c("edit my")["replacement"], '"my notes.txt" ')
        self.assertEqual(self.c("cd My")["replacement"], '"My Docs' + os.sep)
        self.assertEqual(self.c('edit "my')["replacement"], '"my notes.txt" ')

    def test_hidden_only_when_asked(self):
        self.assertNotIn(".hidden", self.c("run ")["items"])
        self.assertEqual(self.c("run .h")["replacement"], ".hidden ")

    def test_subfolder_and_dirs_first(self):
        self.assertEqual(self.c("run sub/in")["replacement"], "sub/inner.py ")
        items = self.c("cd ")["items"]
        self.assertTrue(items[0].endswith(os.sep))          # folders sort first

    def test_no_match(self):
        r = self.c("run zzz")
        self.assertIsNone(r["replacement"])
        self.assertEqual(r["items"], [])

    @unittest.skipUnless(POSIX, "posix home")
    def test_tilde(self):
        self.assertEqual(self.c("cd ~")["replacement"], "~/")

    def test_cursor_in_the_middle(self):
        r = self.c("run al xyz", cursor=6)
        self.assertEqual((r["start"], r["end"], r["replacement"]), (4, 6, "alpha"))


if __name__ == "__main__":
    unittest.main()
