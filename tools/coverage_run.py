#!/usr/bin/env python3
"""
Stdlib line coverage (ADR 0003): runs unittest suites under sys.settrace and
measures the product modules. The threshold lives in
`tools/coverage-threshold.txt` and is a ratchet: it may only go up
(enforced by tests/unit/test_ratchets.py).

  python tools/coverage_run.py tests/unit tests/integration          # run + enforce
  python tools/coverage_run.py --raise-threshold tests/unit tests/integration
"""

from __future__ import annotations

import ast
import dis
import os
import sys
import threading
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [ROOT / "activity_imitator.py", ROOT / "activity_imitator_gui.py"]
THRESHOLD_FILE = ROOT / "tools" / "coverage-threshold.txt"
PRAGMA = "pragma: no cover"


def read_threshold() -> float:
    return float(THRESHOLD_FILE.read_text().split()[0])


def executable_lines(path: Path) -> set[int]:
    source = path.read_text(encoding="utf-8")
    lines: set[int] = set()
    todo = [compile(source, str(path), "exec")]
    while todo:
        code = todo.pop()
        lines.update(ln for _, ln in dis.findlinestarts(code) if ln)
        todo.extend(c for c in code.co_consts if isinstance(c, types.CodeType))
    excluded: set[int] = set()
    src_lines = source.splitlines()
    for node in ast.walk(ast.parse(source)):
        if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
            continue
        first = src_lines[node.lineno - 1]
        is_main_guard = (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                         and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__")
        if PRAGMA in first or is_main_guard:
            excluded.update(range(node.lineno, node.end_lineno + 1))
    return lines - excluded


class Tracer:
    def __init__(self, targets: list[Path]):
        self.files = {os.path.realpath(t): t for t in targets}
        self.hits: dict[str, set[int]] = {os.path.realpath(t): set() for t in targets}

    def global_trace(self, frame, event, arg):
        fn = os.path.realpath(frame.f_code.co_filename)
        if fn in self.files:
            hits = self.hits[fn]

            def local(frame, event, arg):
                if event == "line":
                    hits.add(frame.f_lineno)
                return local
            if event == "call":
                hits.add(frame.f_lineno)
            return local
        return None

    def install(self):
        threading.settrace(self.global_trace)
        sys.settrace(self.global_trace)

    def remove(self):
        sys.settrace(None)
        threading.settrace(None)


def report(tracer: Tracer) -> float:
    total_exec = total_hit = 0
    for real, path in tracer.files.items():
        exe = executable_lines(path)
        hit = exe & tracer.hits[real]
        total_exec += len(exe)
        total_hit += len(hit)
        pct = 100.0 * len(hit) / len(exe) if exe else 100.0
        print(f"  {path.relative_to(ROOT)}: {pct:5.1f}%  ({len(hit)}/{len(exe)} lines)")
    total = 100.0 * total_hit / total_exec if total_exec else 100.0
    print(f"  TOTAL: {total:.1f}%")
    return total


def main(argv: list[str]) -> int:
    raise_threshold = "--raise-threshold" in argv
    suites = [a for a in argv if not a.startswith("--")] or ["tests/unit", "tests/integration"]
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    tracer = Tracer(TARGETS)
    tracer.install()
    try:
        loader = unittest.TestLoader()
        suite = unittest.TestSuite(loader.discover(s, top_level_dir=str(ROOT)) for s in suites)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    finally:
        tracer.remove()
    print("coverage:")
    total = report(tracer)
    threshold = read_threshold()
    if not result.wasSuccessful():
        return 1
    if total + 1e-9 < threshold:
        print(f"coverage: FAILED, {total:.1f}% < threshold {threshold:.1f}% ({THRESHOLD_FILE.name})")
        return 1
    new = float(int(total))
    if raise_threshold and new > threshold:
        THRESHOLD_FILE.write_text(f"{new:.0f}\n")
        print(f"coverage: threshold raised {threshold:.0f}% -> {new:.0f}% (commit it)")
    elif new > threshold:
        print(f"coverage: OK; threshold can be raised to {new:.0f}% (make ratchet-coverage)")
    else:
        print(f"coverage: OK (threshold {threshold:.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
