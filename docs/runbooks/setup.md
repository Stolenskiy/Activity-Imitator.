# Runbook: set up a machine

Use when: first work on a machine, or `make verify` fails with import errors.

1. Check the interpreter: `python3 --version` must be 3.10+ (developed on 3.12).
2. Create the venv and install `requirements.txt`: `make setup` (needs network; the only
   network step in this repo).
3. Check device access (needed only to run the app, not the tests):
   - `getfacl /dev/uinput` lists your user with `rw` (systemd-logind grants it to the seat user);
   - `id -nG` contains `input`; otherwise the owner runs `sudo usermod -aG input $USER` and logs
     in again. Never run sudo yourself.
4. Activate the repo hooks: `make install-hooks` (sets `core.hooksPath` to `tools/hooks/`;
   `tools/hooks/pre-commit` and `tools/hooks/commit-msg` run `tools/guard.py`).
5. Run `make verify` and compare its time with the budget in `AGENTS.md`.
6. Optional, with the owner's OK: desktop launcher, see `docs/runbooks/install-launcher.md`.
7. Update documentation: if any step differed on this machine, fix this runbook and add a
   gotcha to `docs/gotchas.md` in the same commit.
