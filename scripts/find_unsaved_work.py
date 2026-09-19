"""Find GT work that exists only on this disk.

Walks a drive (default ``D:/``) two levels deep for git checkouts, follows
each repository's registered worktrees, and classifies every checkout by what
GitHub does not have:

- ``UNPUSHED``    commits on any local branch (or HEAD) reachable from no remote
- ``UNCOMMITTED`` real edits to tracked files, or new untracked files
- ``SAFE``        everything is on a remote

Line-ending-only edits and tool caches are not work and are ignored, so a
checkout does not look dirty just because Windows touched it. Folders that
match the watch patterns but are not git checkouts are listed separately:
they are, by definition, not on GitHub.

    python -m scripts.find_unsaved_work --write docs/internal/UNSAVED_WORK.md
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ROOT = Path("D:/")
DEFAULT_WATCH = ["*gt*", "*GT*", "*har*", "Groundtruth", "release"]
# A checkout counts as GT work if one of its remotes points at a GT repository,
# whatever its folder is called; a local-only checkout is judged by its name.
GT_REMOTE_MARKERS = ("gt-harness", "groundtruth", "gt-index", "deep-swe")
GT_NAME_PATTERNS = ("gt-*", "gt_*", "*groundtruth*", "har*", "*-gt", "w")
CACHE_PARTS = {
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    ".hypothesis", ".venv", "node_modules",
}
SCAN_DEPTH = 2
SAMPLE_LIMIT = 6
VERDICT_ORDER = {"UNPUSHED": 0, "UNCOMMITTED": 1, "ERROR": 2, "SAFE": 3}


@dataclass(frozen=True)
class CheckoutReport:
    path: Path
    branch: str
    verdict: str
    unpushed: int = 0
    changed: list[str] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)
    last_edit: str = ""
    error: str = ""


def _git(path: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"git {args[0]} failed")
    return done.stdout


def _is_cache(rel: str) -> bool:
    return any(part in CACHE_PARTS for part in rel.replace("\\", "/").split("/"))


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def _last_edit(path: Path, rels: list[str]) -> str:
    times = []
    for rel in rels:
        try:
            times.append((path / rel).stat().st_mtime)
        except OSError:
            continue
    if not times:
        return ""
    return _dt.datetime.fromtimestamp(max(times)).strftime("%Y-%m-%d %H:%M")


def _has_remote(path: Path) -> bool:
    return bool(_git(path, "remote").strip())


def _unpushed(path: Path) -> int:
    """Commits reachable from this checkout's HEAD that no remote has."""
    exclude = ["--not", "--remotes"] if _has_remote(path) else []
    return int(_git(path, "rev-list", "--count", "HEAD", *exclude).strip() or 0)


def local_only_branches(path: Path) -> list[tuple[str, int]]:
    """Local branches (any worktree of this repo) with commits on no remote.

    Reported per repository, not per checkout: worktrees share one ref store,
    so counting them per checkout repeats a single finding many times.
    """
    if not _has_remote(path):
        return []
    found: list[tuple[str, int]] = []
    for name in _lines(_git(path, "for-each-ref", "--format=%(refname:short)", "refs/heads/")):
        count = int(_git(path, "rev-list", "--count", name, "--not", "--remotes").strip() or 0)
        if count:
            found.append((name, count))
    return sorted(found)


def _changed(path: Path) -> list[str]:
    names = _lines(_git(path, "diff", "HEAD", "--ignore-cr-at-eol", "--name-only"))
    # A line-ending-only edit still lists the name; keep only real content changes.
    return [
        rel for rel in names
        if not _is_cache(rel)
        and _git(path, "diff", "HEAD", "--ignore-cr-at-eol", "--", rel).strip()
    ]


def _untracked(path: Path) -> list[str]:
    out = _git(path, "ls-files", "--others", "--exclude-standard", "--directory")
    return [rel.rstrip("/") for rel in _lines(out) if not _is_cache(rel)]


def inspect_checkout(path: Path) -> CheckoutReport:
    """Classify one checkout; never raises (errors become an ERROR verdict)."""
    try:
        branch = _git(path, "branch", "--show-current").strip() or "(detached)"
        changed = _changed(path)
        untracked = _untracked(path)
        unpushed = _unpushed(path)
    except (RuntimeError, OSError, ValueError) as exc:
        return CheckoutReport(path=path, branch="?", verdict="ERROR", error=str(exc)[:200])
    if unpushed:
        verdict = "UNPUSHED"
    elif changed or untracked:
        verdict = "UNCOMMITTED"
    else:
        verdict = "SAFE"
    return CheckoutReport(
        path=path, branch=branch, verdict=verdict, unpushed=unpushed,
        changed=changed, untracked=untracked,
        last_edit=_last_edit(path, changed + untracked),
    )


def fetch_remotes(path: Path) -> bool:
    """Refresh remote-tracking refs; False when a remote is unreachable.

    Without this a clone that never fetched reports commits as UNPUSHED that
    another clone pushed long ago - a false alarm that wastes a real search.
    """
    try:
        _git(path, "fetch", "--all", "--prune", "--quiet")
    except (RuntimeError, OSError):
        return False
    return True


def is_gt_checkout(path: Path) -> bool:
    """True when this checkout belongs to the GT work, by remote or by name."""
    try:
        remotes = _git(path, "remote", "-v").lower()
    except (RuntimeError, OSError):
        remotes = ""
    if remotes:
        return any(marker in remotes for marker in GT_REMOTE_MARKERS)
    name = path.name.lower()
    return any(fnmatch.fnmatch(name, pat) for pat in GT_NAME_PATTERNS)


def _has_git(folder: Path) -> bool:
    """True for a checkout; an unreadable folder (e.g. D:/WpSystem) is not one."""
    try:
        return (folder / ".git").exists()
    except OSError:
        return False


def _subfolders(folder: Path) -> list[Path]:
    try:
        return [p for p in folder.iterdir() if p.is_dir() and not p.name.startswith("$")]
    except OSError:
        return []


def _children(root: Path, depth: int) -> list[Path]:
    """Folders up to ``depth`` levels below ``root``, not descending into checkouts."""
    found: list[Path] = []
    frontier = [root]
    for _ in range(depth):
        level = [child for folder in frontier for child in _subfolders(folder)]
        found.extend(level)
        frontier = [p for p in level if not _has_git(p)]
    return found


def _worktrees(repo: Path) -> list[Path]:
    try:
        out = _git(repo, "worktree", "list", "--porcelain")
    except RuntimeError:
        return []
    prefix = "worktree "
    return [Path(line[len(prefix):]) for line in out.splitlines() if line.startswith(prefix)]


def discover(root: Path, watch: list[str]) -> tuple[list[Path], list[Path]]:
    """Return (git checkouts, watched non-git top-level folders) under ``root``."""
    checkouts: set[Path] = set()
    loose: list[Path] = []
    for folder in _children(root, SCAN_DEPTH):
        if _has_git(folder):
            checkouts.add(folder.resolve())
            checkouts.update(p.resolve() for p in _worktrees(folder) if p.exists())
        elif folder.parent == root and any(fnmatch.fnmatch(folder.name, pat) for pat in watch):
            loose.append(folder)
    return sorted(checkouts), sorted(loose)


def _sample(items: list[str]) -> str:
    shown = ", ".join(f"`{item}`" for item in items[:SAMPLE_LIMIT])
    extra = len(items) - SAMPLE_LIMIT
    return shown + (f" and {extra} more" if extra > 0 else "")


def _render_at_risk(report: CheckoutReport) -> list[str]:
    lines = [f"### `{report.path}` - {report.verdict}", "", f"- Branch: `{report.branch}`"]
    if report.unpushed:
        lines.append(f"- Commits on no remote: {report.unpushed}")
    if report.changed:
        lines.append(f"- Edited tracked files ({len(report.changed)}): {_sample(report.changed)}")
    if report.untracked:
        lines.append(f"- New untracked entries ({len(report.untracked)}): {_sample(report.untracked)}")
    if report.last_edit:
        lines.append(f"- Last edit: {report.last_edit}")
    if report.error:
        lines.append(f"- Error: {report.error}")
    return lines + [""]


def render(
    reports: list[CheckoutReport],
    loose: list[Path],
    stamp: str,
    fetched: bool = False,
    unreachable: list[Path] | None = None,
    branches: dict[Path, list[tuple[str, int]]] | None = None,
) -> str:
    ordered = sorted(reports, key=lambda r: (VERDICT_ORDER.get(r.verdict, 9), str(r.path)))
    at_risk = [r for r in ordered if r.verdict != "SAFE"]
    out = [
        "# Unsaved GT work: what exists only on this disk",
        "",
        f"Generated {stamp} by "
        "`python -m scripts.find_unsaved_work --write docs/internal/UNSAVED_WORK.md`.",
        "Re-run it instead of searching by hand. Anything below that is not SAFE is",
        "lost if the disk is cleaned: commit it, push it to a branch, and add the",
        "branch to `docs/GT_BRANCH_INDEX.md`.",
        "",
        f"**{len(at_risk)} of {len(ordered)} checkouts hold work that is not on GitHub.**"
        " Local-only branches are listed once per repository, after the checkouts.",
        "",
        (
            "Remote-tracking refs were refreshed before this scan (`--fetch`)."
            if fetched else
            "Run with `--fetch` for a trustworthy answer: without it a clone that "
            "never fetched reports commits as UNPUSHED that are already on GitHub."
        ),
        "",
        "## Checkouts that need saving",
        "",
    ]
    for report in at_risk:
        out += _render_at_risk(report)
    if not at_risk:
        out += ["None.", ""]
    for repo, found in sorted((branches or {}).items()):
        if not found:
            continue
        out += [f"### `{repo}` - local-only branches", ""]
        out += [f"- `{name}`: {count} commit(s) on no remote" for name, count in found]
        out += [""]
    if unreachable:
        out += ["## Could not reach their remotes (verdicts below may be stale)", ""]
        out += [f"- `{p}`" for p in unreachable] + [""]
    out += ["## Watched folders that are not git (never on GitHub)", ""]
    out += [f"- `{p}`" for p in loose] or ["None."]
    out += ["", "## Checkouts already safe", ""]
    out += [f"- `{r.path}` (`{r.branch}`)" for r in ordered if r.verdict == "SAFE"] or ["None."]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find GT work that exists only on this disk.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--watch", nargs="*", default=DEFAULT_WATCH)
    parser.add_argument("--write", type=Path, help="write the markdown report here")
    parser.add_argument(
        "--fetch", action="store_true",
        help="refresh remote-tracking refs first (slow, needs network, avoids false alarms)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="report every checkout found, not only GT ones",
    )
    args = parser.parse_args(argv)
    checkouts, loose = discover(args.root, args.watch)
    gt_checkouts = [p for p in checkouts if args.all or is_gt_checkout(p)]
    stale: list[Path] = []
    if args.fetch:
        stale = [p for p in gt_checkouts if not fetch_remotes(p)]
    reports = [inspect_checkout(p) for p in gt_checkouts]
    repos: dict[Path, list[tuple[str, int]]] = {}
    for path in gt_checkouts:
        try:
            repo = Path(_git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()).parent
        except (RuntimeError, OSError):
            continue
        if repo not in repos:
            repos[repo] = local_only_branches(path)
    text = render(
        reports, loose, _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        fetched=args.fetch, unreachable=stale, branches=repos,
    )
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    return 1 if any(r.verdict != "SAFE" for r in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
