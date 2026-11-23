# Status

## Done
- v1–v3: console imitator, PySide6 GUI, uinput input with auto-pause (tags `v1-console`,
  `v2-gui-xtest`, `v3-uinput`).
- Agentic setup: `AGENTS.md`, `make verify`/`make check`, doc-sync tests, guard hooks,
  runbooks, skills, ADRs, size and coverage ratchets.
- Fixed: the listener thread died on the first device read error (`evdev.error` does not exist).

## In progress
- Nothing.

## Next
- Top of `docs/ROADMAP.md`: P1 split `activity_imitator_gui.py` into modules.

## Known limitations
- `activity_imitator_gui.py` exceeds 300 lines (baselined) and cannot grow until split.
- No CI yet: ADR 0007 is Proposed; run `make check` before merging.
- Uncovered by tests: tray icon code and `main()` (single-instance socket); offscreen Qt has no tray.
- On Wayland, cursor movement can only be verified by the owner watching the screen.
- Not yet seen by a human: the tray icon on the COSMIC panel; a full run with real clicks.
- Lint has no line-length or undefined-name checks (ADR 0003).

## Decisions
- [0001 — Agent docs: one entry point, enforced by tests](decisions/0001-agent-docs-single-entry-point.md)
- [0002 — Make is the task runner](decisions/0002-make-as-task-runner.md)
- [0003 — Stdlib-only dev tooling](decisions/0003-stdlib-tooling.md)
- [0004 — Inject input through uinput, not XTest](decisions/0004-uinput-input-backend.md)
- [0005 — Auto-pause replaces the corner fail-safe](decisions/0005-auto-pause-replaces-corner-failsafe.md)
- [0006 — Size and coverage ratchets instead of a mass refactor](decisions/0006-size-and-coverage-ratchets.md)
- [0007 — CI runs `make check`](decisions/0007-ci-workflow.md)
- [0008 — Tests never touch real devices, network or home](decisions/0008-tests-never-touch-hardware.md)
- [0009 — Per-branch status notes](decisions/0009-branch-notes.md)
