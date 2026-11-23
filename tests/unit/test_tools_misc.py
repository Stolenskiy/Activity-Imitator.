"""tools/: install_launcher (temp HOME), manual_cursor_test (dry-run + fakes),
coverage_run helpers and docsync helpers."""

import ast
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import activity_imitator as core
import evdev
from evdev import ecodes
from tests import HardwareAccessError
from tests.fakes import FakeUInput
from tools import coverage_run, docsync, install_launcher, manual_cursor_test


def run(main, *argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(list(argv))
    return code, out.getvalue()


class InstallLauncherTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.launcher = self.home / ".local/bin/activity-imitator-launch"

    def test_dry_run_writes_nothing(self):
        code, out = run(install_launcher.main, "--home", str(self.home))
        self.assertEqual((code, out.count("create")), (0, 4))
        self.assertIn("DRY-RUN", out)
        self.assertFalse(self.launcher.exists())

    def test_apply_renders_templates_and_is_idempotent(self):
        run(install_launcher.main, "--home", str(self.home), "--apply")
        desktop = (self.home / "Desktop/activity-imitator.desktop").read_text()
        self.assertIn(f"Exec={self.launcher}", desktop)
        self.assertIn(f"Path={install_launcher.ROOT}", desktop)
        self.assertNotRegex(desktop + self.launcher.read_text(), r"@[A-Z]+@")
        self.assertTrue(os.access(self.launcher, os.X_OK))
        _, out = run(install_launcher.main, "--home", str(self.home))
        self.assertEqual(out.count("unchanged"), 4)

    def test_changed_files_show_a_diff(self):
        run(install_launcher.main, "--home", str(self.home), "--apply")
        self.launcher.write_text("#!/bin/sh\necho old\n")
        icon = self.home / ".local/share/icons/hicolor/scalable/apps/activity-imitator.svg"
        icon.write_bytes(b"\0binary")
        _, out = run(install_launcher.main, "--home", str(self.home))
        self.assertIn("-echo old", out)
        self.assertIn("binary content differs", out)

    def test_desktop_dir_resolution(self):
        d = install_launcher.desktop_dir
        self.assertEqual(d(self.home, "/x", False), Path("/x"))
        self.assertEqual(d(self.home, None, True), self.home / "Desktop")
        with mock.patch.object(install_launcher.shutil, "which", return_value="/usr/bin/xdg-user-dir"), \
                mock.patch.object(install_launcher.subprocess, "run",
                                  return_value=SimpleNamespace(stdout="/srv/Desk\n")):
            self.assertEqual(d(self.home, None, False), Path("/srv/Desk"))


class ManualToolTest(unittest.TestCase):
    def test_dry_runs_touch_nothing(self):
        for argv in ([], ["--keys"]):
            code, out = run(manual_cursor_test.main, *argv)
            self.assertEqual(code, 0)
            self.assertIn("DRY-RUN", out)

    def test_confirm_really_uses_hardware(self):
        with self.assertRaises(HardwareAccessError):
            run(manual_cursor_test.main, "--confirm", "--lead", "0")

    def test_cursor_circles_with_fake_device(self):
        FakeUInput.created.clear()
        with mock.patch.object(core, "UInput", FakeUInput), mock.patch.object(core.time, "sleep"):
            run(manual_cursor_test.main, "--confirm", "--lead", "0")
        pointer = FakeUInput.created[0]
        self.assertGreater(len(pointer.written), 400)
        self.assertTrue(pointer.closed)

    def test_capslock_self_check(self):
        class Kbd:
            name = "real keyboard"

            def __init__(self, states):
                self.states = iter(states)

            def capabilities(self):
                return {ecodes.EV_LED: [ecodes.LED_CAPSL]}

            def leds(self):
                return next(self.states)
        for states, expected in (([[], [1], []], 0), ([[], [], []], 1)):
            with mock.patch.object(evdev, "list_devices", return_value=["k"]), \
                    mock.patch.object(evdev, "InputDevice", return_value=Kbd(states)), \
                    mock.patch.object(evdev, "UInput", FakeUInput), mock.patch("time.sleep"):
                self.assertEqual(run(manual_cursor_test.main, "--keys", "--confirm")[0], expected)
        with mock.patch.object(evdev, "list_devices", return_value=[]):
            self.assertEqual(run(manual_cursor_test.main, "--keys", "--confirm")[0], 1)


class CoverageHelpersTest(unittest.TestCase):
    def test_executable_lines_skip_main_guard_and_pragma(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.py"
            path.write_text("def f():\n    return 1\n\n\ndef g():  # pragma: no cover\n    return 2\n\n\n"
                            "if __name__ == '__main__':\n    f()\n")
            lines = coverage_run.executable_lines(path)
        self.assertIn(2, lines)
        self.assertFalse({5, 6, 9, 10} & lines)

    def test_tracer_records_calls_and_lines_of_targets_only(self):
        target = Path(core.__file__)
        tracer = coverage_run.Tracer([target])
        first, second = sorted(coverage_run.executable_lines(target))[:2]
        frame = SimpleNamespace(f_code=SimpleNamespace(co_filename=str(target)), f_lineno=first)
        local = tracer.global_trace(frame, "call", None)
        frame.f_lineno = second
        local(frame, "line", None)
        self.assertEqual(tracer.hits[os.path.realpath(target)], {first, second})
        other = SimpleNamespace(f_code=SimpleNamespace(co_filename="/elsewhere.py"), f_lineno=1)
        self.assertIsNone(tracer.global_trace(other, "call", None))
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertGreater(coverage_run.report(tracer), 0)
        self.assertIn("TOTAL", out.getvalue())
        self.assertGreater(coverage_run.read_threshold(), 0)


class DocsyncHelpersTest(unittest.TestCase):
    MD = "# T\n\n## A\n\n| K | V |\n|---|---|\n| `a` | `1` |\n\n### Sub\n\ntext\n\n## B\n\nno table\n"

    def test_section_and_table(self):
        head, rows = docsync.table(docsync.section(self.MD, "A"))
        self.assertEqual((head, rows), (["K", "V"], [["`a`", "`1`"]]))
        self.assertIn("Sub", docsync.section(self.MD, "A"))
        with self.assertRaises(KeyError):
            docsync.section(self.MD, "Missing")
        with self.assertRaises(ValueError):
            docsync.table(docsync.section(self.MD, "B"))

    def test_repo_path_heuristics(self):
        yes = ["tools/lint.py", "Makefile", "README.md", "docs/", ".gitignore"]
        no = ["/dev/uinput", "~/.config/x.json", "0.15", "evdev", "Ctrl+Alt+S", "$HOME/x", "a b.py",
              "docs/runbooks/<topic>.md", "core.InputSimulator"]
        self.assertEqual([t for t in yes if not docsync.looks_like_repo_path(t)], [])
        self.assertEqual([t for t in no if docsync.looks_like_repo_path(t)], [])

    def test_commands_and_targets(self):
        md = "Run `make verify`.\n\n```bash\nmake check APPLY=1  # make nothing\n" \
             ".venv/bin/python tools/lint.py x.py\n```\n"
        self.assertEqual(docsync.make_invocations(md), {"verify", "check", "nothing"})
        self.assertEqual(docsync.command_scripts(md), {"tools/lint.py", "x.py"})

    def test_home_path_expression(self):
        tree = ast.parse("APP = 'app'\nP = Path.home() / '.config' / APP / 's.json'\nQ = Path('/x') / 'y'\n")
        self.assertEqual(docsync.home_path_expr(tree, "P"), "~/.config/app/s.json")
        with self.assertRaises(ValueError):
            docsync.home_path_expr(tree, "Q")

    def test_branch_helpers(self):
        self.assertEqual(docsync.branch_note("feat/x"), "docs/status/feat-x.md")
        with mock.patch.dict(os.environ, {"BRANCH": "main"}):
            self.assertEqual(docsync.current_branch(), "main")
        self.assertIsNone(docsync.git("definitely-not-a-git-command"))


if __name__ == "__main__":
    unittest.main()
