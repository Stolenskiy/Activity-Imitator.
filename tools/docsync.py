"""
Parsing helpers for the doc-sync tests (tests/unit/test_doc_sync_*.py).
Stdlib only; reads sources via AST (never imports product code).

Conventions enforced through these helpers (stated in AGENTS.md):
  * only backticked tokens that look like repo paths are checked as paths;
    external paths are written in full (`~/...`, `/dev/...`) and skipped, as are
    generated outputs under build/ and .venv/;
  * commands are taken only from fenced code blocks;
  * documented tables have fixed header columns.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH_EXTENSIONS = {"py", "md", "txt", "svg", "json", "sh", "in", "desktop", "yml", "yaml",
                   "toml", "cfg", "ini", "png"}
FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.S | re.M)
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.M)


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def doc_files() -> list[str]:
    found = ["AGENTS.md", "CLAUDE.md", "README.md"]
    found += sorted(str(p.relative_to(ROOT)) for p in (ROOT / "docs").rglob("*.md"))
    found += sorted(str(p.relative_to(ROOT)) for p in (ROOT / ".claude" / "skills").rglob("*.md"))
    return [f for f in found if (ROOT / f).exists()]


def fenced_blocks(md: str) -> list[str]:
    return FENCE.findall(md)


def strip_fenced(md: str) -> str:
    return FENCE.sub("", md)


def backticks(md: str) -> list[str]:
    return [t for t in re.findall(r"`([^`\n]+)`", strip_fenced(md)) if t.strip()]


def section(md: str, title: str) -> str:
    """Body of the first heading whose text equals `title`, up to the next heading
    of the same or higher level. Raises KeyError if missing."""
    for m in HEADING.finditer(md):
        if m.group(2) == title:
            level = len(m.group(1))
            rest = md[m.end():]
            for n in HEADING.finditer(rest):
                if len(n.group(1)) <= level:
                    return rest[:n.start()]
            return rest
    raise KeyError(title)


def table(text: str) -> tuple[list[str], list[list[str]]]:
    """First markdown table in `text` -> (header cells, rows)."""
    rows = [ln.strip() for ln in strip_fenced(text).splitlines() if ln.strip().startswith("|")]
    if len(rows) < 2:
        raise ValueError("no markdown table found")
    cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
    return cells[0], [r for r in cells[2:] if r]


def unbacktick(cell: str) -> str:
    return cell.strip().strip("`")


def looks_like_repo_path(token: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", token) or re.fullmatch(r"[\d.]+", token):
        return False
    if token.startswith(("/", "~", "$", "-", ".venv", "build/")) or "://" in token:
        return False
    if token == "Makefile" or "/" in token:
        return True
    ext = token.rsplit(".", 1)[-1] if "." in token else ""
    return ext in PATH_EXTENSIONS or token in {".gitignore"}


def repo_path_exists(token: str) -> bool:
    return (ROOT / token.rstrip("/")).exists()


def makefile_targets() -> set[str]:
    return set(re.findall(r"^([a-z][a-z0-9_-]*):", read("Makefile"), re.M))


def make_invocations(md: str) -> set[str]:
    texts = fenced_blocks(md) + backticks(md)
    return {t for text in texts for t in re.findall(r"\bmake\s+([a-z][a-z0-9_-]*)", text)}


def command_scripts(md: str) -> set[str]:
    """Repo scripts referenced by commands in fenced blocks (`x.py`, `tools/x.py`)."""
    out = set()
    for block in fenced_blocks(md):
        for line in block.splitlines():
            line = line.split("#", 1)[0]
            out.update(t for t in re.findall(r"(?<![\w/.~$-])([\w./-]+\.py)\b", line)
                       if not t.startswith(".venv"))
    return out


def module(rel: str) -> ast.Module:
    return ast.parse(read(rel))


def constants(tree: ast.Module) -> dict[str, object]:
    """Module-level UPPER_CASE assignments whose value is a literal."""
    out: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name.isupper():
                try:
                    out[name] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    return out


def class_node(tree: ast.Module, name: str) -> ast.ClassDef:
    return next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == name)


def dataclass_fields(tree: ast.Module, name: str) -> dict[str, object]:
    out = {}
    for node in class_node(tree, name).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            out[node.target.id] = ast.literal_eval(node.value)
    return out


def class_attr(tree: ast.Module, cls: str, attr: str) -> ast.expr:
    for node in class_node(tree, cls).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == attr for t in node.targets):
            return node.value
    raise KeyError(f"{cls}.{attr}")


def top_level_classes(tree: ast.Module) -> list[str]:
    return [n.name for n in tree.body if isinstance(n, ast.ClassDef)]


def home_path_expr(tree: ast.Module, name: str) -> str:
    """Evaluate `X = Path.home() / "a" / CONST / "b"` to "~/a/<CONST value>/b"."""
    consts = constants(tree)
    node = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name)
    parts: list[str] = []
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        right = node.right
        parts.append(right.value if isinstance(right, ast.Constant) else str(consts[right.id]))
        node = node.left
    if not (isinstance(node, ast.Call) and ast.unparse(node) == "Path.home()"):
        raise ValueError(f"{name} is not Path.home()-based")
    return "~/" + "/".join(reversed(parts))


def git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None


def current_branch() -> str:
    for var in ("BRANCH", "GITHUB_HEAD_REF", "GITHUB_REF_NAME", "CI_COMMIT_BRANCH"):
        if os.environ.get(var):
            return os.environ[var]
    return (git("rev-parse", "--abbrev-ref", "HEAD") or "HEAD").strip()


def file_at(rev: str, rel: str) -> str | None:
    return git("show", f"{rev}:{rel}")


def line_count(rel: str) -> int:
    return len(read(rel).splitlines())


def branch_note(branch: str) -> str:
    return f"docs/status/{branch.replace('/', '-')}.md"
