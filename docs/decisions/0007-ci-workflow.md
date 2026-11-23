# 0007 — CI runs `make check`

Status: Proposed (2026-11-23) — awaiting the owner; there is no remote yet.

## Context
`make check` is defined as exactly what CI runs. No CI exists, so CI-only rules (empty
`docs/status/` on main) run inside `make check` locally today.

## Decision (proposed)
Add a workflow file .github/workflows/check.yml (not created yet) once a GitHub remote exists:
`on: [push, pull_request]`; job on `ubuntu-24.04`: `actions/checkout@v4` with
`fetch-depth: 0` (tags and `main` for ratchets); `actions/setup-python@v5` with 3.12;
`sudo apt-get install -y libegl1 libxkbcommon0 libfontconfig1 libdbus-1-3 linux-libc-dev`
(PySide6 offscreen, evdev build); then `make setup && make check` with env
`RATCHET_BASE=origin/main` and `BRANCH=${{ github.head_ref || github.ref_name }}`.

## Consequences
- Local and CI checks cannot diverge: CI calls the same Make target.
- Until accepted, nothing enforces checks on push; `make check` before merge is a workflow rule.
