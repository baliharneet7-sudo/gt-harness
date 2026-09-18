"""The SWE-Live grader must never fabricate the patch it grades.

Run 35256147148 lost two tasks to a manufactured empty patch. Pier's collect
stage only runs when the trial survives, and on a trial that errored the
evaluator step created an EMPTY file and submitted it - scoring reward 0 while
the model's committed work sat in agent/gt-worktree.patch beside it
(amoffat__sh-744: 4,660 committed bytes, committed_patch_empty false, and the
harness had already recorded collected_patch_will_be_empty false).

The selection is shell inside the workflow, so these tests run that exact
snippet against fixture trees rather than a paraphrase of it.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


def _bash() -> str | None:
    """A POSIX bash. On Windows the bare name resolves to WSL, which cannot
    see the test tree, so prefer Git's bash when it is installed."""
    for candidate in (
        os.environ.get("GT_TEST_BASH"),
        shutil.which("bash") if os.name != "nt" else None,
        "C:/Program Files/Git/bin/bash.exe",
        "C:/Program Files (x86)/Git/bin/bash.exe",
        "/bin/bash",
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


BASH = _bash()

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "swelive_gt_harness_paid.yaml"


def _selection_snippet() -> str:
    """The PATCH_FILE/PATCH_SOURCE selection, lifted from the workflow."""
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index('PATCH_FILE="$(find results/swelive -path')
    end = text.index('PATCH_BYTES=', start)
    body = text[start:end]
    return "\n".join(line[10:] if line.startswith(" " * 10) else line
                     for line in body.splitlines())


def _run(tmp_path: Path) -> tuple[str, str]:
    script = f'set -u\nRUNNER_TEMP="{tmp_path}/tmp"\nmkdir -p "$RUNNER_TEMP"\n' \
             + _selection_snippet() + '\necho "SOURCE=$PATCH_SOURCE"\n' \
             + 'echo "BYTES=$(wc -c < "$PATCH_FILE" | tr -d " ")"\n'
    out = subprocess.run([BASH, "-c", script], cwd=tmp_path,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    src = re.search(r"SOURCE=(\S+)", out.stdout).group(1)
    return src, re.search(r"BYTES=(\d+)", out.stdout).group(1)


def _make(tmp_path: Path, rel: str, content: str) -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    # newline='' keeps byte counts exact: Windows would otherwise expand
    # each line ending and the size assertions would drift.
    with open(p, 'w', encoding='utf-8', newline='') as handle:
        handle.write(content)


@pytest.mark.skipif(not WORKFLOW.is_file() or not BASH, reason="workflow or bash absent")
def test_official_collection_wins_when_pier_collected(tmp_path):
    """The canonical object is preferred whenever it exists."""
    _make(tmp_path, "results/swelive/t/artifacts/model.patch", "diff --git a/x b/x\n")
    _make(tmp_path, "results/swelive/t/agent/gt-worktree.patch", "diff --git a/y b/y\nEXTRA\n")
    source, _ = _run(tmp_path)
    assert source == "official_collection"


@pytest.mark.skipif(not WORKFLOW.is_file() or not BASH, reason="workflow or bash absent")
def test_harness_export_is_graded_when_collection_never_ran(tmp_path):
    """The regression this fix exists for: real work, no collect stage."""
    committed = "diff --git a/sh.py b/sh.py\n+_return_cmd fix\n"
    _make(tmp_path, "results/swelive/t/agent/gt-worktree.patch", committed)
    source, size = _run(tmp_path)
    assert source == "harness_export"
    assert int(size) == len(committed), "the real patch must be graded, not an empty file"


@pytest.mark.skipif(not WORKFLOW.is_file() or not BASH, reason="workflow or bash absent")
def test_absent_is_recorded_rather_than_disguised(tmp_path):
    """With nothing to grade the source says so; an empty patch is still empty."""
    source, size = _run(tmp_path)
    assert source == "absent"
    assert int(size) == 0


@pytest.mark.skipif(not WORKFLOW.is_file() or not BASH, reason="workflow or bash absent")
def test_an_empty_harness_export_is_not_mistaken_for_work(tmp_path):
    """A zero-byte export must not be selected: -size +0 excludes it."""
    _make(tmp_path, "results/swelive/t/agent/gt-worktree.patch", "")
    source, size = _run(tmp_path)
    assert source == "absent"
    assert int(size) == 0
