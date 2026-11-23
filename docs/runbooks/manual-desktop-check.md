# Runbook: check real input on the desktop

Use when: a change affects real devices (`UInputBackend`, `SafetyListener`) and tests with
fakes are not enough. Needs the owner; tests never do this (ADR 0008).

1. Keys, no owner needed but ask first: `make manual-keys-test` shows the plan; with the
   owner's OK `make manual-keys-test CONFIRM=1` toggles Caps Lock twice through a virtual
   keyboard and checks the real keyboards' LEDs (`tools/manual_cursor_test.py`).
2. Cursor, the owner must watch: tell them what will happen, then run
   `make manual-cursor-test CONFIRM=1`. It waits 8 s, then draws two ellipses on the monitor
   that has the cursor. Ask what they saw only after it ended (see `docs/gotchas.md`).
3. Full app: the owner starts `.venv/bin/python activity_imitator_gui.py`, presses start,
   leaves the mouse for a minute and reads the log.
4. Update documentation: record results in `docs/STATUS.md` (Known limitations) or your branch
   note; add surprises to `docs/gotchas.md`.
5. Run `make verify`.
