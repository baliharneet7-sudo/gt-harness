# Internal: how we know nothing is left only on this disk

Work kept dying in two ways: a review worktree was deleted with commits that
were never pushed, and the same search ("what did we not commit?") was redone
by hand every few days. Two files end that.

| File | What it is | How it is produced |
|---|---|---|
| `docs/GT_BRANCH_INDEX.md` | The map: every GT branch on GitHub, the checkouts kept on disk and why, what is done, what is left. | Written by hand; update it when a branch is created or a checkout is removed. |
| `docs/internal/UNSAVED_WORK.md` | The scan: every GT checkout on this machine, classified by what GitHub does not have. | Generated: `python -m scripts.find_unsaved_work --fetch --write docs/internal/UNSAVED_WORK.md` |

## The routine

1. **Before deleting anything** (a worktree, a folder, a whole drive sweep) run
   the scanner with `--fetch`. It exits non-zero while any checkout is not SAFE.
2. **Save what it lists.** Commit the edits, push the branch, and prefer an
   `archive/<date>/<name>` branch for work that is not going anywhere else.
3. **Record the branch** in `docs/GT_BRANCH_INDEX.md`, then remove the worktree
   with `git worktree remove`, never `rm -rf`.
4. **Re-run the scanner** and commit the regenerated report, so the file in git
   always shows the last known state.

## What the verdicts mean

- **UNPUSHED** - commits reachable from that checkout's HEAD that no remote has.
  Losing the folder loses the commits.
- **UNCOMMITTED** - real edits to tracked files, or new untracked files. Tool
  caches and line-ending-only changes are not counted, so Windows touching a
  file does not raise a false alarm.
- **SAFE** - everything is on a remote.
- **Local-only branches** are listed once per repository, not once per checkout,
  because worktrees of one repository share a single ref store.

## Two things the scan cannot tell you

- **Without `--fetch` it lies in your favour.** A clone that never fetched
  reports commits as UNPUSHED that were pushed from elsewhere long ago.
- **"On no remote" is about branches, not about GitHub's object store.** A
  commit can exist on GitHub inside a pull request or a deleted branch and still
  be reachable from no remote branch here. Check with
  `gh api repos/<owner>/<repo>/commits/<sha>` before deciding it is lost.

## Scope

The scanner walks `D:/` two levels deep, follows each repository's registered
worktrees, and keeps only GT checkouts: those whose remotes point at a GT
repository, or, for a checkout with no remote, whose folder name looks like GT
work. Pass `--all` to see every checkout on the drive instead.
