# 0001 — Agent docs: one entry point, enforced by tests

Status: Accepted (2026-11-23)

## Context
Several agents (Claude, Codex, humans) continue the work. Docs that rely on discipline rot,
and duplicated instructions drift apart.

## Decision
- `AGENTS.md` is the only entry point (<= 80 lines); `CLAUDE.md` is just `@AGENTS.md`.
- Agent docs (AGENTS, runbooks, ADRs, STATUS, gotchas) are in English; `README.md` stays
  Ukrainian because it is for the owner and users.
- Every documented surface has a machine-readable source of truth (AST of the code, the
  Makefile, git tags) and README tables use fixed columns, so `tests/unit/test_doc_sync_*.py`
  can compare them mechanically.
- Skills are thin pointers to `docs/runbooks/`.

## Consequences
- Forgetting to update docs fails `make verify`.
- Facts live in one place: numbers were removed from README prose in favour of tables.
