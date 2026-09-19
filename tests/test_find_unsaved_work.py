"""find_unsaved_work: every checkout is classified by what GitHub does not have."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import find_unsaved_work as fuw


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture()
def clone(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(remote), str(work))
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "t")
    _git(work, "config", "core.autocrlf", "false")
    _git(work, "config", "core.hooksPath", str(tmp_path / "nohooks"))
    (work / "a.txt").write_bytes(b"one\ntwo\n")
    _git(work, "add", "a.txt")
    _git(work, "commit", "-q", "-m", "init")
    _git(work, "push", "-q", "origin", "HEAD")
    return work


def test_clean_pushed_checkout_is_safe(clone: Path) -> None:
    assert fuw.inspect_checkout(clone).verdict == "SAFE"


def test_real_edit_is_uncommitted(clone: Path) -> None:
    (clone / "a.txt").write_bytes(b"one\nchanged\n")
    report = fuw.inspect_checkout(clone)
    assert report.verdict == "UNCOMMITTED"
    assert report.changed == ["a.txt"]


def test_line_ending_only_change_is_not_work(clone: Path) -> None:
    (clone / "a.txt").write_bytes(b"one\r\ntwo\r\n")
    assert fuw.inspect_checkout(clone).verdict == "SAFE"


def test_new_file_is_uncommitted(clone: Path) -> None:
    (clone / "new.py").write_text("x = 1\n")
    report = fuw.inspect_checkout(clone)
    assert report.verdict == "UNCOMMITTED"
    assert report.untracked == ["new.py"]


def test_cache_directories_are_ignored(clone: Path) -> None:
    (clone / "__pycache__").mkdir()
    (clone / "__pycache__" / "a.pyc").write_bytes(b"x")
    assert fuw.inspect_checkout(clone).verdict == "SAFE"


def test_commit_not_on_any_remote_is_unpushed(clone: Path) -> None:
    (clone / "a.txt").write_bytes(b"one\ntwo\nthree\n")
    _git(clone, "commit", "-q", "-am", "local only")
    report = fuw.inspect_checkout(clone)
    assert report.verdict == "UNPUSHED"
    assert report.unpushed == 1


def test_work_on_another_local_branch_is_reported_per_repository(clone: Path) -> None:
    """A branch nobody checked out still holds work; report it once, by name."""
    _git(clone, "switch", "-q", "-c", "side")
    (clone / "b.txt").write_text("b\n")
    _git(clone, "add", "b.txt")
    _git(clone, "commit", "-q", "-m", "side work")
    _git(clone, "switch", "-q", "-")
    assert fuw.inspect_checkout(clone).unpushed == 0
    assert fuw.local_only_branches(clone) == [("side", 1)]


def test_a_repository_with_everything_pushed_has_no_local_only_branch(clone: Path) -> None:
    assert fuw.local_only_branches(clone) == []


def test_discovery_finds_nested_checkouts_and_non_git_folders(
    tmp_path: Path, clone: Path
) -> None:
    (tmp_path / "gt-notes").mkdir()
    (tmp_path / "unrelated").mkdir()
    checkouts, loose = fuw.discover(tmp_path, ["gt-*"])
    assert clone.resolve() in checkouts
    assert [p.name for p in loose] == ["gt-notes"]


def test_markdown_lists_unsaved_first_and_names_the_verdicts(clone: Path) -> None:
    (clone / "a.txt").write_bytes(b"one\nchanged\n")
    text = fuw.render([fuw.inspect_checkout(clone)], [], "2026-09-19 00:00")
    assert "UNCOMMITTED" in text
    assert "a.txt" in text
    assert "python -m scripts.find_unsaved_work" in text


def test_unreadable_system_folder_is_skipped_not_fatal(
    tmp_path: Path, clone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "WpSystem").mkdir()
    real_exists = Path.exists

    def exists(self: Path, *args: object, **kwargs: object) -> bool:
        if self.parent.name == "WpSystem":
            raise OSError(1337, "The security ID structure is invalid")
        return real_exists(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", exists)
    checkouts, _ = fuw.discover(tmp_path, ["gt-*"])
    assert clone.resolve() in checkouts


def _remote_is(work: Path, url: str) -> None:
    _git(work, "remote", "set-url", "origin", url)


def test_a_checkout_of_an_unrelated_repo_is_not_gt(clone: Path) -> None:
    _remote_is(clone, "https://github.com/someone/unrelated.git")
    assert fuw.is_gt_checkout(clone) is False


def test_a_checkout_of_a_gt_repo_is_gt_whatever_its_folder_is_called(clone: Path) -> None:
    _remote_is(clone, "https://github.com/harneet2512/gt-harness.git")
    assert fuw.is_gt_checkout(clone) is True


def test_a_groundtruth_producer_checkout_is_gt(clone: Path) -> None:
    _remote_is(clone, "https://github.com/harneet2512/groundtruth.git")
    assert fuw.is_gt_checkout(clone) is True


def test_a_gt_named_folder_with_no_remote_is_gt(tmp_path: Path) -> None:
    work = tmp_path / "gt-scratch"
    work.mkdir()
    _git(work, "init", "-q")
    assert fuw.is_gt_checkout(work) is True


def test_fetch_refreshes_stale_remote_tracking_refs(tmp_path: Path, clone: Path) -> None:
    """A clone that never fetched shows another clone's pushes as missing."""
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(tmp_path / "remote.git"), str(other))
    _git(other, "config", "user.email", "t@example.com")
    _git(other, "config", "user.name", "t")
    (other / "c.txt").write_text("c\n")
    _git(other, "add", "c.txt")
    _git(other, "commit", "-q", "-m", "elsewhere")
    _git(other, "push", "-q", "origin", "HEAD:refs/heads/side")

    assert "side" not in _git(clone, "branch", "-r")
    assert fuw.fetch_remotes(clone) is True
    assert "side" in _git(clone, "branch", "-r")


def test_fetch_of_an_unreachable_remote_is_reported_not_raised(clone: Path) -> None:
    _git(clone, "remote", "set-url", "origin", str(clone / "does-not-exist.git"))
    assert fuw.fetch_remotes(clone) is False


def test_markdown_names_local_only_branches_once_per_repository(clone: Path) -> None:
    text = fuw.render([], [], "2026-09-19 00:00", branches={clone: [("side", 3)]})
    assert "side" in text and "3" in text
