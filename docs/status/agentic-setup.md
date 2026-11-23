# Branch agentic-setup

## Done
- Refactor: `HOTKEYS` constant, unused imports removed, `start()` guarded on init errors,
  listener read-error crash fixed (`evdev.EvdevError`).
- Tooling: `Makefile`, `tools/` (lint, guard, coverage, docsync, launcher, screenshots,
  manual checks), hooks in `tools/hooks/`.
- Tests: `tests/unit`, `tests/integration`, boundary in `tests/__init__.py`.
- Docs: `AGENTS.md`, `CLAUDE.md`, README tables, runbooks, skills, ADRs, STATUS, ROADMAP, gotchas.

## Next
- Fold into `docs/STATUS.md`, delete this note, fast-forward `main`.

## Risks
- The size ratchet blocks growth of `activity_imitator_gui.py` until ROADMAP P1 is done.
