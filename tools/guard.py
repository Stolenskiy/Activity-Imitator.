#!/usr/bin/env python3
"""
Boundary guard (stdlib regex scanning; ADR 0003). Blocks forbidden files,
secrets, API keys, personal emails and home paths from entering git.

  python3 tools/guard.py --all        # tracked + new non-ignored files (make verify)
  python3 tools/guard.py --staged     # staged blobs (pre-commit hook)
  python3 tools/guard.py --message F  # commit message file (commit-msg hook)

A line containing `guard: allow` is skipped; justify it in the same line.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOW = "guard: allow"
MAX_BYTES = 2 * 1024 * 1024

FORBIDDEN_PATHS = [
    (r"(^|/)\.?venv/", "virtualenv"),
    (r"(^|/)__pycache__/|\.py[co]$", "Python bytecode"),
    (r"(^|/)build/", "build output"),
    (r"(^|/)\.env($|\.)", "dotenv file"),
    (r"\.(pem|key|p12|pfx|jks|keystore)$", "key/certificate file"),
    (r"(^|/)id_(rsa|dsa|ecdsa|ed25519)", "SSH key"),
    (r"(^|/)(\.netrc|\.pypirc|credentials\.json)$", "credentials file"),
    (r"(^|/)\.claude/settings(\.local)?\.json$", "agent-tool configuration"),
    (r"(^|/)\.claude/hooks/", "agent-tool hook configuration"),
]

SECRET_PATTERNS = [
    (r"-----BEGIN (RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY", "private key"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key"),
    (r"\bgh[pousr]_[A-Za-z0-9]{30,}", "GitHub token"),
    (r"\bgithub_pat_[A-Za-z0-9_]{20,}", "GitHub token"),
    (r"\bsk-ant-[A-Za-z0-9_\-]{20,}", "Anthropic API key"),
    (r"\bsk-(proj-)?[A-Za-z0-9]{32,}", "OpenAI API key"),
    (r"\bxox[abprs]-[A-Za-z0-9-]{10,}", "Slack token"),
    (r"\bAIza[0-9A-Za-z_\-]{35}\b", "Google API key"),
    (r"(?i)\b(api[_-]?key|secret|access[_-]?token|passw(or)?d)\b\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']",
     "hard-coded credential"),
    (r"(/home|/Users)/(?!user/|<)[A-Za-z0-9._-]+/", "personal home path"),
]

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b")
EMAIL_ALLOWED = re.compile(r"(?i)^(no-?reply@|.*@(\S+\.)?(example\.(com|org|net)|users\.noreply\.github\.com)$)")


def scan_path(path: str) -> list[str]:
    return [f"{path}: forbidden file ({why})" for rx, why in FORBIDDEN_PATHS if re.search(rx, path)]


def scan_text(label: str, text: str) -> list[str]:
    problems = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if ALLOW in line:
            continue
        for rx, why in SECRET_PATTERNS:
            if re.search(rx, line):
                problems.append(f"{label}:{lineno}: {why}")
        for m in EMAIL.finditer(line):
            if not EMAIL_ALLOWED.match(m.group(0)):
                problems.append(f"{label}:{lineno}: email address (personal data)")
    return problems


def scan_blob(path: str, data: bytes) -> list[str]:
    problems = scan_path(path)
    if len(data) > MAX_BYTES:
        problems.append(f"{path}: file larger than {MAX_BYTES // 1024 // 1024} MB")
    elif b"\0" not in data:
        problems += scan_text(path, data.decode("utf-8", errors="replace"))
    return problems


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def all_files() -> list[tuple[str, bytes]]:
    names = _git("ls-files", "-z", "--cached", "--others", "--exclude-standard").decode().split("\0")
    return [(n, (ROOT / n).read_bytes()) for n in names if n and (ROOT / n).is_file()]


def staged_files() -> list[tuple[str, bytes]]:
    names = _git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR").decode().split("\0")
    return [(n, _git("show", f":{n}")) for n in names if n]


def main(argv: list[str]) -> int:
    if argv[:1] == ["--message"] and len(argv) == 2:
        problems = scan_text("commit message", Path(argv[1]).read_text(encoding="utf-8"))
    elif argv in ([], ["--all"]):
        problems = [p for name, data in all_files() for p in scan_blob(name, data)]
    elif argv == ["--staged"]:
        problems = [p for name, data in staged_files() for p in scan_blob(name, data)]
    else:
        print(__doc__, file=sys.stderr)
        return 2
    for p in problems:
        print(p)
    if problems:
        print(f"guard: BLOCKED, {len(problems)} problem(s). Remove them; never bypass with --no-verify.",
              file=sys.stderr)
        return 1
    print("guard: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
