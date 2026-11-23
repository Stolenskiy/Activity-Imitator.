# Runbook: merge a branch into main

Use when: a feature branch (and its worktree) is done. The branch note is required on the
branch and forbidden on main (ADR 0009), so it is folded right after the merge, on main.

1. On the branch: `make check` green; the note `docs/status/<branch>.md` lists done/next/risks.
2. Get the owner's OK, then `git switch main` and `git merge --ff-only <branch>`. If main has
   moved on, rebase or merge only with the owner's OK; never force.
3. Fold the note into `docs/STATUS.md` (Done, Next, Known limitations; keep <= 40 lines) and move
   promised work into `docs/ROADMAP.md` with a priority. Delete the note with `git rm`.
4. Update documentation: if the branch added ADRs, the Decisions list in `docs/STATUS.md` must
   mirror `docs/decisions/` (tested).
5. Run `make verify` (now on main: `docs/status/` must hold no notes), then `make check`.
6. Commit the fold on main. Removing the worktree (`git worktree remove`) or deleting the
   branch needs the owner's OK.
