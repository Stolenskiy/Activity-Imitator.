"""Ratchets and branch rules (ADR 0006, ADR 0009).

Bases compared against: $RATCHET_BASE (default HEAD) and `main` when on another branch.
"""

import os
import re
import unittest

from tools import docsync

ROOT = docsync.ROOT
LIMIT = 300
BASELINE = "docs/size-baseline.txt"
THRESHOLD = "tools/coverage-threshold.txt"
SOURCE = re.compile(r"(\.py|\.sh|\.in)$|^Makefile$|^tools/hooks/")


def parse_baseline(text):
    out = {}
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            path, count = line.rsplit(None, 1)
            out[path] = int(count)
    return out


def source_files():
    listed = docsync.git("ls-files", "--cached", "--others", "--exclude-standard") or ""
    return [p for p in listed.split("\n") if p and SOURCE.search(p) and (ROOT / p).is_file()]


def bases():
    branch = docsync.current_branch()
    revs = [os.environ.get("RATCHET_BASE", "HEAD")]
    if branch not in ("main", "HEAD") and docsync.git("rev-parse", "--verify", "--quiet", "main"):
        revs.append("main")
    return revs


class SizeRatchetTest(unittest.TestCase):
    def test_source_files_within_limit_or_exactly_baselined(self):
        baseline = parse_baseline(docsync.read(BASELINE))
        problems = []
        for path in source_files():
            lines = docsync.line_count(path)
            if path in baseline:
                if lines != baseline[path]:
                    hint = "lower its baseline entry" if lines < baseline[path] else \
                        "move code into a new module; baselined files must not grow"
                    problems.append(f"{path}: {lines} lines, baseline {baseline[path]} -> {hint}")
            elif lines > LIMIT:
                problems.append(f"{path}: {lines} lines > {LIMIT}; split it (new files get no baseline)")
        for path, count in baseline.items():
            if not (ROOT / path).is_file():
                problems.append(f"{BASELINE}: stale entry {path}; remove it")
            elif count <= LIMIT:
                problems.append(f"{BASELINE}: {path} is within the limit now; remove its entry")
        self.assertEqual(problems, [])

    def test_baseline_only_shrinks(self):
        current = parse_baseline(docsync.read(BASELINE))
        for rev in bases():
            old_text = docsync.file_at(rev, BASELINE)
            if old_text is None:
                continue
            old = parse_baseline(old_text)
            for path, count in current.items():
                self.assertIn(path, old, f"{BASELINE}: new entry {path} vs {rev} (never add entries)")
                self.assertLessEqual(count, old[path], f"{BASELINE}: {path} raised vs {rev}")


class CoverageRatchetTest(unittest.TestCase):
    def test_threshold_only_rises(self):
        current = float(docsync.read(THRESHOLD).split()[0])
        self.assertGreater(current, 0)
        for rev in bases():
            old = docsync.file_at(rev, THRESHOLD)
            if old is not None:
                self.assertGreaterEqual(current, float(old.split()[0]), f"{THRESHOLD} lowered vs {rev}")


class BranchNotesTest(unittest.TestCase):
    def test_branch_notes_rule(self):
        branch = docsync.current_branch()
        notes = sorted(p.name for p in (ROOT / "docs" / "status").glob("*.md"))
        if branch == "main":
            self.assertEqual(notes, [], "docs/status/ must be empty on main: fold notes into docs/STATUS.md")
        elif branch != "HEAD":
            self.assertTrue((ROOT / docsync.branch_note(branch)).is_file(),
                            f"branch {branch} needs {docsync.branch_note(branch)} (ADR 0009)")


if __name__ == "__main__":
    unittest.main()
