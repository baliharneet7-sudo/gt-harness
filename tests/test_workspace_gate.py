"""Per-workspace gating of GT's code-repo guidance (gt_engine.workspace_gate).

Campaign 2026-09-29 (same model, space-bunny-alpha): on Terminal-Bench 2.0 the
code-repo workflow ("gt-query first", "gt-impact", write tests) and the submit
review were applied to QEMU / data / ops workspaces with no repository, and the
review flagged every task literal as "[not in your changes]" because it diffs
against git (qemu-startup rep4). These tests pin the gate that keeps that
guidance to real code repositories.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from gt_engine.attached_delivery import attached_instance_template, instance_template_for
from gt_engine.submit_review import session_review
from gt_engine.workspace_gate import MIN_SOURCE_FILES, is_code_workspace, lacks_repository

STOCK = (
    "Please solve this issue: {{task}}\n\n"
    "## Recommended Workflow\n\n1. Analyze the codebase\n"
    "2. Submit: `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`\n\n"
    "## Command Execution Rules\n\nOne command per response.\n"
    "<example_response>\nls -la\n</example_response>\n"
)


def _git_repo(root: Path, n_sources: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(n_sources):
        (root / f"mod_{i}.py").write_text(f"def f{i}():\n    return {i}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
                    "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"], check=True)
    return root


def test_the_threshold_is_inclusive(tmp_path):
    assert not is_code_workspace(str(_git_repo(tmp_path / "below", MIN_SOURCE_FILES - 1)))
    assert is_code_workspace(str(_git_repo(tmp_path / "at", MIN_SOURCE_FILES)))


def test_a_subdirectory_of_a_code_repo_counts_the_whole_repo(tmp_path):
    repo = _git_repo(tmp_path / "repo", MIN_SOURCE_FILES)
    sub = repo / "docs"
    sub.mkdir()

    assert is_code_workspace(str(sub))


def test_a_git_error_other_than_no_repository_keeps_gt_on(monkeypatch, tmp_path):
    """A container whose repo is owned by another user fails `git rev-parse` with
    "dubious ownership"; the gate must fail open, never silently drop GT."""
    from gt_engine import workspace_gate

    def dubious(_cwd, *_args):
        return subprocess.CompletedProcess(
            ["git"], 128, "", "fatal: detected dubious ownership in repository at '/app'")

    monkeypatch.setattr(workspace_gate, "_git", dubious)

    assert workspace_gate.is_code_workspace(str(tmp_path))
    assert not workspace_gate.lacks_repository(str(tmp_path))


def test_a_git_timeout_keeps_gt_on(monkeypatch, tmp_path):
    from gt_engine import workspace_gate

    monkeypatch.setattr(workspace_gate, "_git", lambda _cwd, *_args: None)

    assert workspace_gate.is_code_workspace(str(tmp_path))


def test_the_gate_decision_is_reported(tmp_path):
    from gt_engine.workspace_gate import gate_report

    report = gate_report(str(tmp_path))

    assert report == {"code_workspace": False, "repository": "none", "tracked_source_files": 0}


def test_a_workspace_without_git_is_not_a_code_workspace(tmp_path):
    (tmp_path / "alpine.iso").write_bytes(b"\0" * 16)
    for i in range(MIN_SOURCE_FILES + 5):
        (tmp_path / f"s{i}.c").write_text("int main(){return 0;}\n", encoding="utf-8")

    assert lacks_repository(str(tmp_path))
    assert not is_code_workspace(str(tmp_path))


def test_a_git_repo_with_enough_sources_is_a_code_workspace(tmp_path):
    repo = _git_repo(tmp_path / "repo", MIN_SOURCE_FILES)

    assert not lacks_repository(str(repo))
    assert is_code_workspace(str(repo))


def test_a_git_repo_with_few_sources_is_not_a_code_workspace(tmp_path):
    repo = _git_repo(tmp_path / "tiny", 3)

    assert not lacks_repository(str(repo))
    assert not is_code_workspace(str(repo))


def test_non_code_workspace_keeps_the_stock_task_template(tmp_path):
    template = instance_template_for(STOCK, str(tmp_path))

    assert template == STOCK
    assert "gt-query" not in template


def test_code_workspace_gets_the_gt_workflow(tmp_path):
    repo = _git_repo(tmp_path / "repo", MIN_SOURCE_FILES)

    assert instance_template_for(STOCK, str(repo)) == attached_instance_template(STOCK)


def _bash() -> str:
    """POSIX bash: on Windows the one shipped with Git (System32's bash.exe is WSL)."""
    if os.name != "nt":
        return "bash"
    git = shutil.which("git")
    # git.exe lives in Git\cmd or Git\mingw64\bin; bash.exe in Git\bin.
    candidates = [parent / sub / "bash.exe" for parent in Path(git).parents
                  for sub in ("bin", "usr/bin")] if git else []
    found = next((str(path) for path in candidates if path.is_file()), None)
    if found is None:
        pytest.skip("Git bash not found")
    return found


def _run_prebuild(cwd: Path) -> str:
    from eval.miniswe_thin_agent import prebuild_command

    command = prebuild_command(python="echo GT_BUILD_RAN", state_dir=str(cwd / "state"))
    result = subprocess.run([_bash(), "-c", command], cwd=cwd, capture_output=True, text=True, timeout=60)
    return result.stdout + result.stderr


def test_prebuild_is_skipped_outside_a_git_work_tree(tmp_path):
    (tmp_path / "alpine.iso").write_bytes(b"\0" * 16)

    output = _run_prebuild(tmp_path)

    assert "GT_BUILD_RAN" not in output
    assert "gt prebuild skipped" in output


def test_prebuild_runs_in_a_git_work_tree(tmp_path):
    repo = _git_repo(tmp_path / "repo", 2)

    assert "GT_BUILD_RAN" in _run_prebuild(repo)


def test_prebuild_runs_when_git_fails_for_another_reason(tmp_path):
    from eval.miniswe_thin_agent import prebuild_command

    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    (fake_bin / "git").write_text(
        "#!/bin/sh\necho \"fatal: detected dubious ownership in repository at '$PWD'\" >&2\nexit 128\n",
        encoding="utf-8", newline="\n")
    command = (f'chmod +x "{fake_bin.as_posix()}/git"; PATH="{fake_bin.as_posix()}:$PATH"; '
               + prebuild_command(python="echo GT_BUILD_RAN", state_dir="state"))
    result = subprocess.run([_bash(), "-c", command], cwd=tmp_path, capture_output=True, text=True, timeout=60)

    assert "GT_BUILD_RAN" in result.stdout + result.stderr


def test_submit_review_is_skipped_without_git(tmp_path):
    (tmp_path / "start.sh").write_text("qemu-system-x86_64 -cdrom alpine.iso\n", encoding="utf-8")
    engine = SimpleNamespace(issue_text="Start `alpine.iso` so `telnet 127.0.0.1 6665` shows a login prompt.",
                             repo_root=str(tmp_path))
    session = SimpleNamespace(_engine=engine)

    assert session_review(session, "") == ""
