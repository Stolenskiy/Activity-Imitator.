# 0009 — Per-branch status notes

Status: Accepted (2026-11-23)

## Context
Parallel agents on different branches must not fight over `docs/STATUS.md`, and session
context must survive between agents.

## Decision
Every non-main branch keeps `docs/status/<branch>.md` (`/` becomes `-`) with done / next /
risks. At merge time it is folded into `docs/STATUS.md` and deleted.
`tests/unit/test_ratchets.py` requires the note off main and an empty `docs/status/` on main
(only `.gitkeep`).

## Consequences
- STATUS.md changes only at merge time, which avoids conflicts.
- Branch detection honours `BRANCH`/CI variables, then `git rev-parse`.
