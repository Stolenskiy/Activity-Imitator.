"""tools/lint.py and tools/guard.py. Fake secrets are assembled at runtime so that
the guard never sees a real-looking secret in this file."""

import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tools import guard, lint


def fake(*parts):
    return "".join(parts)


class LintTest(unittest.TestCase):
    def problems(self, src):
        return lint.check_source("x.py", src)

    def test_clean_code_passes(self):
        self.assertEqual(self.problems("import os\nimport os.path\nprint(os.path.join('a'))\n"), [])
        self.assertEqual(self.problems("from __future__ import annotations\n"), [])
        self.assertEqual(self.problems("from a import b\n__all__ = ['b']\n"), [])

    def test_unused_import_is_reported_unless_allowed(self):
        self.assertEqual(self.problems("import os\nimport sys\nprint(os)\n"), ["x.py:2: unused import 'sys'"])
        self.assertEqual(self.problems("import sys  # lint: allow\n"), [])

    def test_risky_constructs_are_reported(self):
        src = "from m import *\ntry:\n    pass\nexcept:\n    pass\nbreakpoint()\nimport pdb\npdb.set_trace()\n"
        text = "\n".join(self.problems(src))
        for needle in ("wildcard import", "bare 'except:'", "breakpoint()", "debugger import"):
            self.assertIn(needle, text)

    def test_whitespace_rules(self):
        text = "\n".join(self.problems("x = 1 \nif x:\n\ty = 2"))
        for needle in ("trailing whitespace", "tab indentation", "missing final newline"):
            self.assertIn(needle, text)

    def test_syntax_error(self):
        self.assertIn("syntax error", self.problems("def (:\n")[0])

    def test_main_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            good, bad = Path(tmp) / "good.py", Path(tmp) / "bad.py"
            good.write_text("x = 1\n")
            bad.write_text("import sys\n")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(lint.main([str(good)]), 0)
                self.assertEqual(lint.main([str(bad)]), 1)

    def test_lists_repository_python_files(self):
        names = {p.name for p in lint.python_files()}
        self.assertTrue({"activity_imitator.py", "lint.py"} <= names)


class GuardContentTest(unittest.TestCase):
    SECRETS = [
        fake("AKIA", "ABCDEFGHIJKLMNOP"),
        fake("gh", "p_", "a" * 36),
        fake("github", "_pat_", "b" * 30),
        fake("sk-", "ant-", "x" * 30),
        fake("sk-", "y" * 40),
        fake("xox", "b-", "1234567890ab"),
        fake("AI", "za", "B" * 35),
        fake("-----BEGIN ", "RSA ", "PRIVATE KEY-----"),
        fake("pass", "word = '", "hunter22hunter", "'"),
        fake("/ho", "me/", "alice/project"),
        fake("alice", "@", "corp.io"),
    ]

    def test_every_secret_kind_is_blocked(self):
        for sample in self.SECRETS:
            self.assertTrue(guard.scan_text("f", f"value: {sample}\n"), sample[:12])

    def test_allowed_lines_and_addresses(self):
        for ok in (fake("no", "reply@", "anthropic.com"), fake("bot", "@", "example.com"),
                   fake("/home/", "user/x"), fake("AKIA", "ABCDEFGHIJKLMNOP  # guard: ", "allow test")):
            self.assertEqual(guard.scan_text("f", ok), [], ok)

    def test_forbidden_paths(self):
        for path in (".venv/lib/x.py", "a/__pycache__/m.pyc", ".env", "keys/server.pem",
                     ".claude/settings.local.json", ".claude/hooks/x.sh", "build/out.png", "id_ed25519"):
            self.assertTrue(guard.scan_path(path), path)
        self.assertEqual(guard.scan_path("docs/STATUS.md"), [])

    def test_large_and_binary_blobs(self):
        self.assertIn("larger than", guard.scan_blob("big.txt", b"a" * (guard.MAX_BYTES + 1))[0])
        self.assertEqual(guard.scan_blob("bin.dat", b"\0" + fake("AKIA", "ABCDEFGHIJKLMNOP").encode()), [])


class GuardModesTest(unittest.TestCase):
    def run_main(self, *argv):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return guard.main(list(argv))

    def test_commit_message_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            msg = Path(tmp) / "MSG"
            msg.write_text("Fix ring\n\nCo-Authored-By: Bot <" + fake("no", "reply@", "example.com") + ">\n")
            self.assertEqual(self.run_main("--message", str(msg)), 0)
            msg.write_text("Fix by " + fake("alice", "@", "corp.io") + "\n")
            self.assertEqual(self.run_main("--message", str(msg)), 1)

    def test_usage_error(self):
        self.assertEqual(self.run_main("--bogus"), 2)

    def test_staged_and_all_modes_in_a_temporary_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True, capture_output=True)
            (Path(tmp) / "ok.txt").write_text("hello\n")
            subprocess.run(["git", "-C", tmp, "add", "ok.txt"], check=True)
            with mock.patch.object(guard, "ROOT", Path(tmp)):
                self.assertEqual(self.run_main("--staged"), 0)
                (Path(tmp) / "leak.txt").write_text(fake("token: ", "AKIA", "ABCDEFGHIJKLMNOP") + "\n")
                self.assertEqual(self.run_main("--all"), 1)
                subprocess.run(["git", "-C", tmp, "add", "leak.txt"], check=True)
                self.assertEqual(self.run_main("--staged"), 1)


if __name__ == "__main__":
    unittest.main()
