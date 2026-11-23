# Runbook: add a simulated action or a safe key

Use when: the imitator should do something new (another gesture, another key).

1. Safety first: only actions that cannot modify content or click outside the safe zone.
   Keys go into `SAFE_KEYS` in `activity_imitator.py` and into `UInputBackend.KEYMAP`
   (codes from `evdev.ecodes`); the virtual keyboard can only type keys listed there.
2. Core: add a method to `InputSimulator` that returns a short detail string; register it in
   `ACTION_WEIGHTS` (weights sum to 1) and dispatch it in `MainLoop.run`.
3. GUI: map it in `ImitatorWorker._pick` and `ImitatorWorker._run`; describe it for the log
   (see `describe_mouse`, `KEY_NAMES`, `KIND_COLORS` in `activity_imitator_gui.py`); add a
   settings toggle via `docs/runbooks/add-setting.md` if users should switch it off.
4. Tests: `tests/unit/test_core_simulator.py` (behaviour with `FakeBackend`),
   `tests/unit/test_core_engine_backend.py` (device events with `FakeUInput`),
   `tests/unit/test_core_consistency.py` (cross-module maps).
5. Update documentation: README tables "Безпека" (new key) and "Структура коду" (new class) in
   `README.md`; doc-sync compares them with `SAFE_KEYS`, `KEY_NAMES` and the AST.
6. Run `make verify`, then `make check`.
7. Real-device behaviour needs the owner: `docs/runbooks/manual-desktop-check.md`.
