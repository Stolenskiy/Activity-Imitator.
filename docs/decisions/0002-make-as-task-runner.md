# 0002 — Make is the task runner

Status: Accepted (2026-11-23)

## Context
The project is a Linux-only Python app (uinput/evdev) with no build system. Agents need one
obvious command set; GNU Make is preinstalled on every target machine.

## Decision
`Makefile` provides `verify`, `check` and helper targets; every target calls a stdlib Python
script in `tools/` so logic stays testable. Paths are relative because the repo path contains
a space.

## Consequences
- No pyproject/tox/nox; `make help` lists everything.
- `tests/unit/test_doc_sync_docs.py` fails if a doc mentions a target that does not exist.
