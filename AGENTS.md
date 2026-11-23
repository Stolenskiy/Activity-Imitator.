# AGENTS.md — Activity Imitator

The single entry point for every agent (Claude, Codex, humans). Read this file, then
only what the Task map names. Do not scan the repository.

## Project
Linux desktop utility that keeps a remote/VDI session alive by imitating mouse and
keyboard activity. Core + CLI: `activity_imitator.py` (uinput virtual devices, evdev
listener). GUI: `activity_imitator_gui.py` (PySide6). User docs (Ukrainian): `README.md`.
Agent docs are English (ADR 0001). Setup details: `docs/runbooks/setup.md`.

```bash
make setup          # once: .venv + requirements.txt (network)
make install-hooks  # once: guard runs on every commit and commit message
make verify         # inner loop, run before you finish anything
make check          # what CI runs; must be green before merging to main
```

## Verify budget
- `make verify`: ~0.7 s (measured 2026-11-23): lint + guard + `tests/unit` incl. doc-sync.
- `make check`: ~5.7 s (measured 2026-11-23): verify + `tests/integration` + coverage >= `tools/coverage-threshold.txt`.
- If `make verify` gets twice as slow, find out why before adding more to it.

## Task map
| Task | Read |
|---|---|
| Set up a machine, hooks | `docs/runbooks/setup.md` |
| Run or debug verify/check, fix a doc-sync failure | `docs/runbooks/verify.md` |
| Add or change a user setting | `docs/runbooks/add-setting.md` |
| Add a new simulated action or key | `docs/runbooks/add-action-type.md` |
| Change GUI states, colours, layout | `docs/runbooks/gui-state-or-visual.md` |
| Check real cursor/keys on the desktop | `docs/runbooks/manual-desktop-check.md` |
| Install or change the desktop launcher | `docs/runbooks/install-launcher.md` |
| Release a version, roll back | `docs/runbooks/release-and-rollback.md` |
| Merge a finished branch into main | `docs/runbooks/merge-branch.md` |
| Current state, next work | `docs/STATUS.md`, `docs/ROADMAP.md` |
| Why things are as they are | `docs/decisions/` |
| Known traps | `docs/gotchas.md` |

Doc conventions (tested): backticked repo paths must exist (write external paths in
full: `~/...`, `/dev/...`; planned files without backticks); commands come from fenced blocks;
README tables have fixed columns and are compared with the code.

## Hard boundaries
1. Never commit secrets, API keys, personal names, emails or home paths; never bypass `tools/guard.py` (`--no-verify`).
2. Never edit or commit `.venv/`, `__pycache__/`, `build/`.
3. Never edit agent-tool configuration (`.claude/settings*.json`, hook configs); instructions and skills only.
4. Tests must never touch real devices (`/dev/uinput`, `/dev/input`), the network or the real home; use `tests/fakes.py`.
5. Nothing that moves the real cursor or writes outside the repo without the owner's OK; such targets are dry-run by default (`make install-launcher`, `make manual-cursor-test`, `make manual-keys-test`).
6. Never push, rewrite history, delete tags or branches, or loosen a ratchet (`docs/size-baseline.txt`, `tools/coverage-threshold.txt`).
7. No external communication (issues, PRs, messages) on the owner's behalf.
8. Never revisit an Accepted ADR or delete a ROADMAP item without the owner; flag instead.
9. No new dependency without an ADR; prefer the standard library.

## Workflow rules
- Every behaviour change ships with a test next to it and the docs it affects.
- Finish with `make verify` green; run `make check` before merging.
- At the end of a session that changed state, update `docs/STATUS.md` (on main) or your branch note.
- Deferred work goes to `docs/ROADMAP.md` with a priority, never only into chat.
- Self-improvement: before finishing, fix the runbook, gotcha or test that would have saved you time, in the same commit.
- Git identity comes from git config; never set it. No names or emails in commit messages.

## Parallel work
- One feature = one branch + worktree: `git worktree add ../ai-<feature> -b feat/<feature>`.
- Each non-main branch keeps `docs/status/<branch>.md` (`/` becomes `-`): done / next / risks. It is required off main and forbidden on main: fold it into `docs/STATUS.md` and delete it when merging.
- Hot files (keep edits small, expect conflicts): `activity_imitator_gui.py` (`MainWindow`), `activity_imitator.py`, `README.md` tables, `Makefile`, `docs/STATUS.md` (merge time only).
- `activity_imitator_gui.py` is at its size baseline: GUI work must not grow it (ROADMAP P1).
