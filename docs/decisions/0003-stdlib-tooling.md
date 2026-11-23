# 0003 — Stdlib-only dev tooling

Status: Accepted (2026-11-23)

## Context
The venv had no pytest, ruff, coverage or gitleaks. New dependencies make agent environments
harder to reproduce.

## Decision
- Tests: `unittest`. Lint: `tools/lint.py` (AST: syntax, unused imports, wildcard, bare except,
  debugger, whitespace). Coverage: `tools/coverage_run.py` (sys.settrace).
  Secret guard: `tools/guard.py` (regex).
- Runtime dependencies stay `evdev` and `PySide6-Essentials` only.

## Consequences
- Lint is weaker than ruff: no line-length, no undefined-name analysis (ROADMAP P3).
- Coverage counts lines, not branches; the threshold is a ratchet (ADR 0006).
- Everything runs with the project venv, no extra installs.
