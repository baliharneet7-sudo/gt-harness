"""Which workspaces get GT's code-repository guidance.

GT's task workflow (``gt-query`` first, ``gt-impact``, write tests) and its
submit review assume a code repository under git. Campaign 2026-09-29
(same model, space-bunny-alpha) applied both to Terminal-Bench 2.0 workspaces
that are an ISO image, a CSV or one C file: the review, which diffs against
git, flagged every task literal as "[not in your changes]" (qemu-startup
rep4), and TB2 agent timeouts ran at 29% against the baseline's 18%.

A workspace qualifies when it is a git work tree tracking at least
``MIN_SOURCE_FILES`` source files. The gate fails OPEN: only git's own "not a
git repository" answer, or a repository with too few sources, turns the
guidance off. Any other git failure (a container repo owned by another user,
a timeout, no git binary) keeps GT fully on. The ``gt-*`` tools stay
available either way.
"""
from __future__ import annotations

import subprocess
from pathlib import PurePosixPath

MIN_SOURCE_FILES = 20
_GIT_TIMEOUT_SECONDS = 15
_NOT_A_REPOSITORY = "not a git repository"
# Program source only: config, docs and shell scripts (which the indexer also
# reads) do not make a workspace a code repository.
CODE_EXTENSIONS = frozenset({
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
    ".scala", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".cs", ".rb", ".php", ".swift",
})

REPOSITORY = "git"
NO_REPOSITORY = "none"
UNKNOWN = "unknown"


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess[str] | None:
    # safe.directory: container repos are often owned by root while the agent
    # runs as another user, and git then refuses every command.
    try:
        return subprocess.run(["git", "-c", "safe.directory=*", "-C", cwd, *args],
                              capture_output=True, text=True,
                              timeout=_GIT_TIMEOUT_SECONDS, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None


def repository_state(cwd: str) -> str:
    """``git``, ``none`` (git itself says there is no repository) or ``unknown``."""
    result = _git(cwd, "rev-parse", "--is-inside-work-tree")
    if result is None:
        return UNKNOWN
    if result.returncode == 0 and result.stdout.strip() == "true":
        return REPOSITORY
    if _NOT_A_REPOSITORY in result.stderr:
        return NO_REPOSITORY
    return UNKNOWN


def lacks_repository(cwd: str) -> bool:
    """True only when git confirms there is no repository here."""
    return repository_state(cwd) == NO_REPOSITORY


def tracked_source_files(cwd: str) -> int | None:
    """Source files tracked anywhere in the repository (``:/`` = from the top,
    ``-z`` = unquoted paths); None when git cannot answer."""
    result = _git(cwd, "ls-files", "-z", "--full-name", "--", ":/")
    if result is None or result.returncode != 0:
        return None
    return sum(1 for path in result.stdout.split("\0")
               if path and PurePosixPath(path).suffix.lower() in CODE_EXTENSIONS)


def gate_report(cwd: str) -> dict[str, object]:
    state = repository_state(cwd)
    if state == NO_REPOSITORY:
        return {"code_workspace": False, "repository": state, "tracked_source_files": 0}
    count = tracked_source_files(cwd) if state == REPOSITORY else None
    code = count is None or count >= MIN_SOURCE_FILES  # unknown: fail open
    return {"code_workspace": code, "repository": state, "tracked_source_files": count}


def is_code_workspace(cwd: str) -> bool:
    return bool(gate_report(cwd)["code_workspace"])


__all__ = ["CODE_EXTENSIONS", "MIN_SOURCE_FILES", "gate_report", "is_code_workspace",
           "lacks_repository", "repository_state", "tracked_source_files"]
