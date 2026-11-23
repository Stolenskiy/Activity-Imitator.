# Runbook: add or change a user setting

Use when: a new option in the GUI settings tab or in `~/.config/activity-imitator/settings.json`.

1. Add the field with a JSON-compatible default to the `Settings` dataclass in
   `activity_imitator_gui.py`. Old settings files keep working: unknown keys are ignored and
   missing keys take the default.
2. Use it where it matters: the loop in `ImitatorWorker` (`_run`, `_pick`,
   `user_wait_remaining`) and/or the UI in `MainWindow._build_settings` (helpers `_row`,
   `Toggle`, `NoWheelSlider`; connect through `MainWindow._set`; reflect it in
   `MainWindow._sync_settings_ui`).
3. Size ratchet: `activity_imitator_gui.py` must not grow (ADR 0006). Compensate by moving code
   out into a new module of at most 300 lines.
4. Tests: persistence in `tests/unit/test_gui_helpers.py`, UI behaviour in
   `tests/unit/test_gui_window.py`, loop behaviour in `tests/integration/test_worker_thread.py`.
5. Update documentation: add a row to the README table "Налаштування" in `README.md`
   (key, JSON default, description). The doc-sync test compares it with `Settings`.
6. Visual change? `make screenshots`, then inspect `build/screenshots/all.png`.
7. Run `make verify`; before merging, `make check`.
