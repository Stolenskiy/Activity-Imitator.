# Gotchas

Housekeeping: when you add an entry, re-read the file and fix or delete stale ones.
Budget: 40 lines (tested by `tests/unit/test_doc_sync_docs.py`).

- XTest/pyautogui through XWayland on COSMIC shows an "Allow remote control?" portal dialog
  on every launch. Use uinput (ADR 0004).
- A new uinput device needs ~1 s before the compositor uses it; `UInputBackend` waits 0.4 s
  (enough in practice for its first, slow action), the Caps Lock self-check waits 1.5 s.
- COSMIC maps absolute uinput coordinates onto the monitor that currently has the cursor.
- Wayland apps cannot read the global cursor position, and a fullscreen test window started
  from a terminal received no pointer or key events. Verify motion with the owner watching;
  give at least 8 s lead time and ask only after the test ends
  (`docs/runbooks/manual-desktop-check.md`).
- Keyboard injection can be verified without the owner via Caps Lock LEDs
  (`make manual-keys-test CONFIRM=1`).
- python-evdev has no `evdev.error` module: catch `evdev.EvdevError`.
- `QTimer.singleShot` called from a non-Qt thread never fires; emit a signal or poll a flag.
- `pkill -f "<pattern>"` also matches the shell that runs it; use a bracket in the pattern,
  e.g. `[.]venv/bin/python activity_imitator_gui`.
- `QSystemTrayIcon.show()` before an icon is set logs "No Icon set"; pass the icon to the
  constructor.
- The repo path contains a space: quote it in shell commands; the Makefile uses relative paths.
- Inside tests HOME is a temp dir (`tests/__init__.py`): `Path.home()` is never the real home.
- Never call `sys.settrace` in tests: `make check` measures coverage with a tracer and a test
  that replaces it silently loses coverage (test the tracer by calling its methods directly).
- PySide6/Qt6 handlers need the exact event class (e.g. `QEnterEvent` for `enterEvent`).
