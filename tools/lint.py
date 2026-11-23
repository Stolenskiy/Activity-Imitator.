#!/usr/bin/env python3
"""
Minimal stdlib-only linter (ADR 0003): no third-party tools required.

Checks every Python file tracked by git (plus new, non-ignored files):
  syntax, unused imports, `import *`, bare `except:`, debugger calls,
  trailing whitespace, tab indentation, missing final newline.

Suppress a finding on one line with a trailing `# lint: allow` comment.
Usage: python3 tools/lint.py [FILE ...]
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOW = "lint: allow"


def python_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.py"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode()
    return [ROOT / p for p in out.split("\0") if p and (ROOT / p).exists()]


def _used_names(tree: ast.AST) -> set[str]:
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            root = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                used.add(root.id)
    for node in ast.walk(tree):  # names exported via __all__ count as used
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                used.update(e.value for e in node.value.elts if isinstance(e, ast.Constant))
    return used


def check_source(path: str, source: str) -> list[str]:
    problems: list[str] = []
    lines = source.splitlines()

    def report(lineno: int, msg: str) -> None:
        line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        if ALLOW not in line:
            problems.append(f"{path}:{lineno}: {msg}")

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno}: syntax error: {exc.msg}"]

    used = _used_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            for alias in node.names:
                if alias.name == "pdb":
                    report(node.lineno, "debugger import 'pdb'")
                if alias.name == "*":
                    report(node.lineno, "wildcard import")
                    continue
                bound = alias.asname or alias.name.split(".")[0]
                if bound not in used:
                    report(node.lineno, f"unused import '{bound}'")
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            report(node.lineno, "bare 'except:' (catch a specific exception)")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "breakpoint":
            report(node.lineno, "debugger call 'breakpoint()'")

    for i, line in enumerate(lines, 1):
        if line != line.rstrip():
            report(i, "trailing whitespace")
        if line.startswith("\t") or line.lstrip(" ").startswith("\t"):
            report(i, "tab indentation")
    if source and not source.endswith("\n"):
        report(len(lines), "missing final newline")
    return problems


def main(argv: list[str]) -> int:
    files = [Path(a).resolve() for a in argv] or python_files()
    problems: list[str] = []
    for f in files:
        rel = f.relative_to(ROOT) if f.is_relative_to(ROOT) else f
        problems += check_source(str(rel), f.read_text(encoding="utf-8"))
    for p in problems:
        print(p)
    if problems:
        print(f"lint: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"lint: {len(files)} files OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
