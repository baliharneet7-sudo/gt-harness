"""Three lessons from TB2 run 35571048690, pinned.

The run lost 9 tasks against its baseline. Six were never graded at all, and
25 more ran without a code graph while the journal said only "unsuccessful".
Every one of those was legible in the artifacts and illegible in the receipts,
which is the difference these tests exist to hold.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gt_engine import indexer
from gt_engine.indexer import IndexBuildStatus
from scripts.miniswe_gt_run import _NON_SUBMITTED_TERMINALS, TERMINAL_EXIT_CODES

# --- A. a killed child is gradable, not an internal error --------------------

def test_a_signal_killed_child_is_conserved_for_the_verifier():
    """Exit 5 makes Pier error the trial, so the verifier never runs.

    caffe-cifar-10, fix-ocaml-gc, reshard-c4-data and write-compressor were all
    SIGKILLed by the container's memory controller (`child_returncode: -9`),
    sealed `internal_error`/5, and graded nothing. write-compressor had already
    been solved. The workspace outlives the process; the verifier is the only
    thing that can price it.
    """
    assert TERMINAL_EXIT_CODES["child_killed"] == 0


def test_a_killed_child_can_never_be_read_as_a_clean_pass():
    """Conserving the run must not manufacture a success."""
    assert "child_killed" in _NON_SUBMITTED_TERMINALS


@pytest.mark.parametrize("returncode", [-9, -15, -6])
def test_the_supervisor_maps_signal_deaths_to_that_terminal(returncode):
    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "miniswe_supervisor.py"
    ).read_text(encoding="utf-8")

    # The branch must test "negative" rather than enumerate signals: a child
    # killed by SIGTERM is in the same position as one killed by SIGKILL.
    assert "result.returncode < 0" in source
    assert 'terminal = "child_killed"' in source
    assert returncode < 0  # the parametrisation documents the intended range


def test_the_signal_branch_precedes_the_exit_code_branch():
    """`-9 in {3,4,5,6,7}` is False, so ordering is what makes the fix work."""
    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "miniswe_supervisor.py"
    ).read_text(encoding="utf-8")

    assert source.index("result.returncode < 0") < source.index(
        "result.returncode in {3, 4, 5, 6, 7}"
    )


# --- C. the patch export keeps its message -----------------------------------

def test_a_failed_patch_export_records_why():
    """`{"type": "ValueError"}` cost four trials' worth of archaeology."""
    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "miniswe_supervisor.py"
    ).read_text(encoding="utf-8")

    assert '"message": str(exc)[:200]' in source


# --- D. an unindexed workspace says why --------------------------------------

def test_a_workspace_with_no_source_names_that_as_the_reason(monkeypatch, tmp_path):
    """25 of 88 tasks ran graphless reporting `error=''`.

    `is_code_repo` returning False is an ordinary answer - a terminal task
    whose workspace holds one data file has nothing to graph - but it is still
    the answer, and it was the single most expensive missing sentence in the
    run.
    """
    monkeypatch.setenv("GT_TASK_ID", "some-task")
    monkeypatch.setenv("GT_PRODUCT_SOURCE_SHA", "2" * 40)
    monkeypatch.setattr(indexer, "is_code_repo", lambda root, **_: False)

    receipt = indexer.ensure_index_with_receipt(str(tmp_path))

    assert receipt.status is IndexBuildStatus.NOT_APPLICABLE
    assert not receipt.success
    assert "no file with an indexable source extension" in receipt.error_diagnostic


def test_the_journal_names_the_status_when_there_is_no_error_type():
    """`error_type="unsuccessful"` is not a diagnosis."""
    source = (
        Path(__file__).resolve().parents[1] / "gt_engine" / "miniswe_integration.py"
    ).read_text(encoding="utf-8")

    # The receipt branch, not the exception branch above it.
    start = source.index('or "unsuccessful"')
    window = source[start - 600:start + 60]
    assert 'getattr(getattr(receipt, "status", ""), "value", "")' in window
    # The bare word survives only as the last resort.
    assert window.index('"status", ""') < window.index('or "unsuccessful"')


def test_a_built_index_is_unaffected(monkeypatch, tmp_path):
    """The diagnosis is added to a non-success path only."""
    monkeypatch.setattr(indexer, "is_code_repo", lambda root, **_: True)
    monkeypatch.setattr(
        indexer, "ensure_index", lambda *a, **k: str(tmp_path / "graph.db")
    )
    (tmp_path / "graph.db").write_text("", encoding="utf-8")

    receipt = indexer.ensure_index_with_receipt(str(tmp_path))

    # This stub graph is not a real database, so the receipt carries its own
    # (correct) complaint. What matters is that it is not the no-source one.
    assert receipt.status is not IndexBuildStatus.NOT_APPLICABLE
    assert "no file with an indexable source extension" not in receipt.error_diagnostic


def test_the_receipt_serialises_its_diagnosis(monkeypatch, tmp_path):
    """The journal reads `as_dict`, so the sentence has to survive it."""
    monkeypatch.setattr(indexer, "is_code_repo", lambda root, **_: False)

    payload = indexer.ensure_index_with_receipt(str(tmp_path)).as_dict()

    assert "no file with an indexable source extension" in json.dumps(payload)
