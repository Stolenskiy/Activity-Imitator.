# Runbook: release a version, roll back

Use when: the owner wants a named version, or something must be undone.

1. On `main` with `make check` green and `docs/status/` empty (branch notes folded).
2. Update `docs/STATUS.md` (Done) and add a row to the README table "Версії й відкат" in
   `README.md`: tag, what it is.
3. With the owner's OK create the tag: `git tag v<N>-<slug>`. There is no remote; never push
   or delete tags without the owner.
4. Run `make verify`: doc-sync checks that every `v*` tag has a README row and vice versa.
5. Roll back (owner decides): inspect with `git switch --detach <tag>`; restore files with
   `git checkout <tag> -- .`; older tags (`v1-console`, `v2-gui-xtest`) also need `pyautogui`.
6. Update documentation: note the rollback in `docs/STATUS.md` and why in a new ADR under
   `docs/decisions/` if it reverses a decision.
