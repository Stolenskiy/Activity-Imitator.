# Runbook: change GUI states or visuals

Use when: a new status, colour, label, layout or widget in `activity_imitator_gui.py`.

1. Tokens and maps live at the top of `activity_imitator_gui.py`: colours, `STATUS_COLORS`,
   `STATUS_TEXT` (same keys, tested), `KIND_COLORS`, `QSS`.
2. State logic: `MainWindow.display_status`, `MainWindow._apply_status` (pill, ring, tray,
   buttons), `MainWindow._tick_anim` (60 fps ring) and `MainWindow._tick_slow` (labels, stats).
3. Painting: `PowerRing.paintEvent`, `StatusPill.paintEvent`, `Toggle.paintEvent`,
   `LogDelegate.paint`.
4. Size ratchet: the file must not grow (ADR 0006); put new widgets in a new module
   (<= 300 lines) and import them.
5. Tests: render every new branch in `tests/unit/test_gui_widgets.py`; state transitions in
   `tests/unit/test_gui_window.py`; add the state to `tools/screenshots.py` if it is new.
6. Look at it: `make screenshots`, then open `build/screenshots/all.png` (stopped, running,
   waiting, paused, settings). Never judge visuals without looking.
7. Update documentation: README "Запуск" bullets and "Структура коду" table in `README.md`.
8. Run `make verify`.
