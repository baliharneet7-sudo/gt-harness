from __future__ import annotations

from pathlib import Path

import pytest

from gt_engine import indexer
from gt_engine.indexer import BenchmarkGraphRequired, ensure_index


@pytest.fixture
def benchmark_run(monkeypatch):
    monkeypatch.setenv("GT_TASK_ID", "arktype-json-schema-refs-dependencies")
    monkeypatch.setenv("GT_PRODUCT_SOURCE_SHA", "2" * 40)


@pytest.fixture
def local_run(monkeypatch):
    monkeypatch.delenv("GT_TASK_ID", raising=False)
    monkeypatch.delenv("GT_PRODUCT_SOURCE_SHA", raising=False)


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "main.go").write_text("package main\n", encoding="utf-8")
    return tmp_path


def test_a_benchmark_run_without_its_graph_is_graded_degraded_not_aborted(
    benchmark_run, monkeypatch, tmp_path: Path
):
    """This used to raise BenchmarkGraphRequired and abort the trial.

    TB2 run 35545356695, write-compressor: a one-file repository whose only
    file the producer could not parse was filed as infrastructure_failed and
    never scored, where the GT-off baseline solved it. Aborting removed the
    task from the graded set on exactly the cases that separate the arms.
    The run now proceeds degraded, journals why, and is graded; the cost of
    a graphless run is bounded by the recovery suspension, not by the abort.
    """
    diagnostics: list[str] = []
    monkeypatch.setattr(indexer, "is_code_repo", lambda root: True)
    monkeypatch.setattr(indexer, "_ensure_index_unlocked", lambda root, state_dir=None, **_: None)

    assert ensure_index(str(_repo(tmp_path)), diagnostics=diagnostics) is None
    assert any("benchmark_graph_unavailable" in row for row in diagnostics)


def test_an_index_that_raises_is_degraded_with_the_fault_named(
    benchmark_run, monkeypatch, tmp_path: Path
):
    def explode(root, state_dir=None, **_):
        raise RuntimeError("gt-index exited 1")

    diagnostics: list[str] = []
    monkeypatch.setattr(indexer, "is_code_repo", lambda root: True)
    monkeypatch.setattr(indexer, "_ensure_index_unlocked", explode)

    assert ensure_index(str(_repo(tmp_path)), diagnostics=diagnostics) is None
    assert any("gt-index exited 1" in row for row in diagnostics)
    assert any("benchmark_graph_unavailable" in row for row in diagnostics)


def test_the_refusal_class_still_exists_for_harness_faults():
    """Source discovery that cannot complete is a harness fault, not a
    repository the producer could not parse; that path still refuses."""
    assert issubclass(BenchmarkGraphRequired, RuntimeError)


def test_a_benchmark_run_with_a_graph_proceeds(benchmark_run, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(indexer, "is_code_repo", lambda root: True)
    monkeypatch.setattr(
        indexer, "_ensure_index_unlocked", lambda root, state_dir=None, **_: "/g/graph.db"
    )

    assert ensure_index(str(_repo(tmp_path))) == "/g/graph.db"


def test_a_task_starting_with_no_source_is_not_a_failure(
    benchmark_run, monkeypatch, tmp_path: Path
):
    """Nothing to index yet — the graph fills as the agent creates files."""

    monkeypatch.setattr(indexer, "is_code_repo", lambda root: False)

    assert ensure_index(str(tmp_path)) is None


def test_local_work_keeps_its_degraded_mode(local_run, monkeypatch, tmp_path: Path):
    """Outside a benchmark a missing graph is deliberate, not a defect."""

    monkeypatch.setattr(indexer, "is_code_repo", lambda root: True)
    monkeypatch.setattr(indexer, "_ensure_index_unlocked", lambda root, state_dir=None, **_: None)

    assert ensure_index(str(_repo(tmp_path))) is None


def test_an_incomplete_benchmark_identity_does_not_trigger_the_refusal(
    monkeypatch, tmp_path: Path
):
    """benchmark_invalid is its own diagnosed condition, not this one."""

    monkeypatch.setenv("GT_TASK_ID", "some-task")
    monkeypatch.delenv("GT_PRODUCT_SOURCE_SHA", raising=False)
    monkeypatch.setattr(indexer, "is_code_repo", lambda root: True)
    monkeypatch.setattr(indexer, "_ensure_index_unlocked", lambda root, state_dir=None, **_: None)

    assert ensure_index(str(_repo(tmp_path))) is None
