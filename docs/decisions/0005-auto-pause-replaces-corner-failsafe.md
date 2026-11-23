# 0005 — Auto-pause replaces the corner fail-safe

Status: Accepted (2026-11-23)

## Context
pyautogui's fail-safe (cursor in a screen corner) needs the cursor position, which Wayland
does not expose; after ADR 0004 it could not work at all.

## Decision
`SafetyListener` records the last real input (keys, motion, touch) from evdev, ignoring our own
virtual devices. While the user is active the imitation pauses; it resumes after
`resume_after` seconds idle (GUI) or `IDLE_RESUME_SECONDS` (CLI). A running mouse motion aborts
when the user takes over.

## Consequences
- The imitator never fights the user for the mouse.
- Needs read access to `/dev/input` (group `input`); without it auto-pause is disabled and the
  GUI says so.
