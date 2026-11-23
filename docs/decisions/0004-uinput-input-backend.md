# 0004 — Inject input through uinput, not XTest

Status: Accepted (2026-11-23)

## Context
pyautogui uses XTest via XWayland. On COSMIC, XWayland runs with `-enable-ei-portal`, so
every launch showed an "Allow remote control?" dialog for an "Unknown application".

## Decision
`UInputBackend` creates two kernel virtual devices via `/dev/uinput`: an absolute pointer and
a small keyboard limited to `SAFE_KEYS`. pyautogui was removed (tag `v3-uinput`).

## Consequences
- No portal dialogs; works on Wayland and X11 without `DISPLAY`.
- The pointer is absolute; COSMIC maps it onto the monitor that has the cursor.
- The cursor position cannot be read on Wayland, so the corner fail-safe was dropped (ADR 0005).
- Requires write access to `/dev/uinput` (logind ACL for the seat user).
