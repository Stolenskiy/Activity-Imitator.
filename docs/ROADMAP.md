# Roadmap

Priorities: P0 urgent, P1 next, P2 planned, P3 nice to have. Agents may only flag an item
(append "— flagged: <reason>"); the owner decides what is removed or re-prioritised.

- **P1** Split `activity_imitator_gui.py` into modules (theme/QSS, widgets, worker, window), each
  <= 300 lines, and drop its entry from `docs/size-baseline.txt`. Unblocks GUI work (ADR 0006)
  and reduces conflicts between parallel agents.
- **P2** CI: adopt the workflow in ADR 0007 once a remote exists.
- **P2** Autostart at login: start minimised to the tray with the imitation off.
- **P2** Schedule: enable the imitation only during working hours.
- **P2** Tests for the tray icon and `main()` single-instance handling (fake tray/socket).
- **P3** Light theme that follows the system.
- **P3** Line-length and undefined-name lint (ADR 0003).
- **P3** Choose the target monitor (today: the monitor that has the cursor).
