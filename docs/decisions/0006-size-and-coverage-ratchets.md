# 0006 — Size and coverage ratchets instead of a mass refactor

Status: Accepted (2026-11-23)

## Context
Limits: source files <= 300 lines, AGENTS.md <= 80, STATUS.md <= 40, ADR <= 25. Two legacy
files exceed 300 lines; splitting them is separate approved work.

## Decision
- `docs/size-baseline.txt` lists legacy violations with their exact line count. Entries may
  only be lowered or removed, never added or raised; a baselined file must match its entry.
- `tools/coverage-threshold.txt` may only go up (`make ratchet-coverage`).
- Both are compared with `RATCHET_BASE` (default `HEAD`; in CI origin/main) and with `main`
  when on another branch (`tests/unit/test_ratchets.py`).

## Consequences
- `activity_imitator_gui.py` cannot grow: GUI work must first move code into new modules
  (ROADMAP P1). New files must meet the limits outright.
