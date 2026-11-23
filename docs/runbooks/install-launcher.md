# Runbook: install or change the desktop launcher

Use when: installing the desktop/menu shortcut or changing `packaging/`.

1. Templates: `packaging/activity-imitator.desktop.in` and
   `packaging/activity-imitator-launch.in`; placeholders `@REPO@`, `@LAUNCHER@`, `@ICON@` are
   filled by `tools/install_launcher.py`. Never hard-code a home path (guard blocks it).
2. Preview, writes nothing: `make install-launcher` (prints create/update/unchanged and diffs).
3. Only with the owner's OK: `make install-launcher APPLY=1`. It writes the launcher, the icon
   from `assets/activity-imitator.svg`, the menu entry and the desktop shortcut under the home.
4. Optional check if available: run `desktop-file-validate` on the installed desktop entry.
5. Tests: `tests/unit/test_tools_misc.py` installs into a temp home.
6. Update documentation: README "Встановлення" in `README.md` and this runbook.
7. Run `make verify`.
