#!/usr/bin/env python3
"""
Install the desktop launcher from `packaging/` templates.

DRY-RUN BY DEFAULT: prints what would be created/updated (with a diff) and
writes nothing. Pass --apply (make install-launcher APPLY=1) to write files
outside the repository -- only with the owner's OK (AGENTS.md, Hard boundaries).

  python3 tools/install_launcher.py [--apply] [--home DIR] [--desktop-dir DIR]
"""

from __future__ import annotations

import argparse
import difflib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = "activity-imitator"


def desktop_dir(home: Path, explicit: str | None, custom_home: bool) -> Path:
    if explicit:
        return Path(explicit)
    if not custom_home and shutil.which("xdg-user-dir"):
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip()
        if out:
            return Path(out)
    return home / "Desktop"


def plan(home: Path, desk: Path) -> list[tuple[Path, bytes, bool]]:
    """-> [(target, content, executable)]"""
    launcher = home / ".local/bin" / f"{APP}-launch"
    icon = home / ".local/share/icons/hicolor/scalable/apps" / f"{APP}.svg"
    subst = {"@REPO@": str(ROOT), "@LAUNCHER@": str(launcher), "@ICON@": str(icon)}

    def render(template: str) -> bytes:
        text = (ROOT / "packaging" / template).read_text(encoding="utf-8")
        for key, value in subst.items():
            text = text.replace(key, value)
        return text.encode()

    desktop = render(f"{APP}.desktop.in")
    return [
        (launcher, render(f"{APP}-launch.in"), True),
        (icon, (ROOT / "assets" / f"{APP}.svg").read_bytes(), False),
        (home / ".local/share/applications" / f"{APP}.desktop", desktop, True),
        (desk / f"{APP}.desktop", desktop, True),
    ]


def describe(target: Path, content: bytes) -> tuple[str, str]:
    if not target.exists():
        return "create", ""
    old = target.read_bytes()
    if old == content:
        return "unchanged", ""
    if b"\0" in old or b"\0" in content:
        return "update", "  (binary content differs)\n"
    diff = difflib.unified_diff(old.decode(errors="replace").splitlines(True),
                                content.decode(errors="replace").splitlines(True),
                                f"{target} (installed)", f"{target} (new)")
    return "update", "".join(diff)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="actually write files")
    ap.add_argument("--home", help="install under this home directory (default: ~)")
    ap.add_argument("--desktop-dir", help="desktop folder (default: xdg-user-dir DESKTOP)")
    args = ap.parse_args(argv)
    home = Path(args.home) if args.home else Path.home()
    desk = desktop_dir(home, args.desktop_dir, bool(args.home))

    changes = 0
    for target, content, executable in plan(home, desk):
        action, diff = describe(target, content)
        print(f"{action:9} {target}")
        if diff:
            print(diff, end="" if diff.endswith("\n") else "\n")
        if action == "unchanged":
            continue
        changes += 1
        if args.apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(0o755 if executable else 0o644)
    if not args.apply:
        print(f"DRY-RUN: {changes} change(s) not written. Re-run with --apply "
              "(make install-launcher APPLY=1) after the owner's OK.")
    else:
        print(f"applied {changes} change(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
