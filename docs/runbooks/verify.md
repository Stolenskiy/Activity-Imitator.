# Runbook: verify, check and fixing failures

Use when: before finishing any change, before merging, or when verify/check fails.

1. Inner loop: `make verify` = `tools/lint.py` + `tools/guard.py --all` + `tests/unit`
   (core, GUI offscreen, doc-sync, ratchets). Budget: `AGENTS.md`.
2. Before merging: `make check` = lint + guard + `tests/unit` and `tests/integration` under
   `tools/coverage_run.py`. It is exactly what CI runs (ADR 0007).
3. Lint failure: fix the code; suppress a deliberate case with `# lint: allow` and a reason.
4. Guard failure: remove the secret, email, home path or forbidden file. A false positive
   gets `guard: allow` plus a reason on that line; never use `--no-verify`.
5. Doc-sync failure (`tests/unit/test_doc_sync_code.py`, `tests/unit/test_doc_sync_docs.py`):
   the message names the doc and the source of truth. Change the doc to match the code, or the
   code if the doc states the intended behaviour. Parsers live in `tools/docsync.py`.
6. Ratchet failure (`tests/unit/test_ratchets.py`):
   - a baselined file changed size: if it shrank, lower its entry in `docs/size-baseline.txt`;
     if it grew, move code into a new module instead;
   - coverage below threshold: add tests; never lower `tools/coverage-threshold.txt`;
   - coverage well above threshold: `make ratchet-coverage` and commit the new value;
   - branch note missing or present on main: see ADR 0009.
7. New documented surface (a new table, constant group, command list)? Add a doc-sync test
   for it in `tests/unit/test_doc_sync_code.py` or `tests/unit/test_doc_sync_docs.py`.
8. Update documentation: if the budget moved noticeably, update `AGENTS.md`; record new traps
   in `docs/gotchas.md`.
9. Run `make verify` again until green.
