from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from gt_engine.repository_graph_service import (
    GRAPH_BUILDER_VERSION,
    GraphNotReadyError,
    GraphReceipt,
    GraphStatus,
    RepositoryGraphService,
    _GraphBuildStats,
    compute_repository_identity,
)
from gt_harness.cli import _graph_receipt_output


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "gt@example.invalid")
    _git(root, "config", "user.name", "GT Test")
    (root / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    _git(root, "add", "app.py")
    _git(root, "commit", "-qm", "initial")
    return root


def _database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE nodes (
                id INTEGER PRIMARY KEY, label TEXT, name TEXT, qualified_name TEXT,
                file_path TEXT, start_line INTEGER, end_line INTEGER, signature TEXT,
                return_type TEXT, is_exported INTEGER, is_test INTEGER, language TEXT,
                parent_id INTEGER, repo_id TEXT
            );
            CREATE TABLE edges (
                id INTEGER PRIMARY KEY, source_id INTEGER, target_id INTEGER, type TEXT,
                source_line INTEGER, source_file TEXT, resolution_method TEXT,
                confidence REAL, metadata TEXT, trust_tier TEXT, candidate_count INTEGER,
                evidence_type TEXT, verification_status TEXT, repo_id TEXT
            );
            INSERT INTO nodes VALUES
              (1,'function','answer','answer','app.py',1,2,'answer()','',1,0,'python',NULL,'repo'),
              (2,'method','helper','Answer.answer','app.py',4,5,'helper()','',0,0,'python',NULL,'repo');
            """
        )
        connection.commit()
    finally:
        connection.close()


def _receipt(root: Path, graph: Path) -> GraphReceipt:
    identity = compute_repository_identity(root)
    return GraphReceipt(
        repository=str(root.resolve()),
        commit_sha=identity.commit_sha,
        branch=identity.branch,
        working_tree_state=identity.working_tree_state,
        source_revision=identity.source_revision,
        graph_schema_version="test-v1",
        graph_builder_version=GRAPH_BUILDER_VERSION,
        build_started="2026-08-22T00:00:00Z",
        build_completed="2026-08-22T00:00:01Z",
        build_status=GraphStatus.READY,
        files_discovered=1,
        files_attempted=1,
        files_indexed=1,
        files_skipped=0,
        files_failed=0,
        symbols=1,
        nodes_by_type={"function": 1},
        edges_by_type={},
        coverage=1.0,
        build_duration_ms=1000.0,
        persistent_graph_path=str(graph),
        graph_checksum_or_identity=RepositoryGraphService.file_sha256(graph),
        query_ready=True,
        degraded_reasons=(),
    )


def test_source_revision_includes_dirty_and_untracked_graph_inputs(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    clean = compute_repository_identity(root)
    assert clean.working_tree_state == "clean"

    (root / "app.py").write_text("def answer():\n    return 43\n", encoding="utf-8")
    modified = compute_repository_identity(root)
    assert modified.commit_sha == clean.commit_sha
    assert modified.source_revision != clean.source_revision
    assert modified.working_tree_state == "dirty"

    (root / "new.py").write_text("from app import answer\n", encoding="utf-8")
    untracked = compute_repository_identity(root)
    assert untracked.source_revision != modified.source_revision


def test_definition_query_is_exact_and_accepts_documented_plural_alias(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    graph = state / "graph.db"
    _database(graph)
    receipt = _receipt(root, graph)
    (state / "graph-receipt.json").write_text(
        json.dumps(receipt.as_dict(), sort_keys=True), encoding="utf-8"
    )
    service = RepositoryGraphService(root, state_dir=state)

    result = service.query("definitions", "answer")

    assert result["mode"] == "definition"
    assert [row["name"] for row in result["evidence"]] == ["answer"]


def test_cli_receipt_is_compact_by_default_and_lossless_when_verbose(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    graph = tmp_path / "graph.db"
    _database(graph)
    service = RepositoryGraphService(root, state_dir=tmp_path / "state")
    receipt = _receipt(root, graph)

    summary = _graph_receipt_output(service, receipt, verbose=False)
    verbose = _graph_receipt_output(service, receipt, verbose=True)

    assert summary["query_ready"] is True
    assert summary["receipt_path"] == str(service.receipt_path)
    assert "graph_input_hashes" not in summary
    assert "graph_input_hashes" in verbose


def test_query_refuses_graph_after_worktree_changes(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    graph = state / "graph.db"
    _database(graph)
    receipt = _receipt(root, graph)
    (state / "graph-receipt.json").write_text(
        json.dumps(receipt.as_dict(), sort_keys=True), encoding="utf-8"
    )
    service = RepositoryGraphService(root, state_dir=state)
    assert service.status().build_status is GraphStatus.READY

    (root / "app.py").write_text("def answer():\n    return 0\n", encoding="utf-8")
    stale = service.status()
    assert stale.build_status is GraphStatus.STALE
    assert stale.query_ready is False
    with pytest.raises(GraphNotReadyError):
        service.query("definition", "answer")


def test_ready_receipt_cannot_claim_missing_or_changed_database(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    graph = state / "graph.db"
    _database(graph)
    receipt = _receipt(root, graph)
    (state / "graph-receipt.json").write_text(
        json.dumps(receipt.as_dict(), sort_keys=True), encoding="utf-8"
    )

    graph.write_bytes(graph.read_bytes() + b"corruption")
    observed = RepositoryGraphService(root, state_dir=state).status()
    assert observed.build_status is GraphStatus.FAILED
    assert observed.query_ready is False
    assert "graph_checksum_mismatch" in observed.degraded_reasons


def test_receipt_rejects_ready_without_query_readiness(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    graph = tmp_path / "graph.db"
    _database(graph)
    with pytest.raises(ValueError):
        replace(_receipt(root, graph), query_ready=False)


def test_discovery_accounting_mismatch_can_never_report_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    graph = state / "graph.db"
    _database(graph)
    monkeypatch.setattr(
        "gt_engine.repository_graph_service.ensure_index_with_receipt",
        lambda *_args, **_kwargs: SimpleNamespace(
            graph_db=str(graph),
            status=SimpleNamespace(value="available"),
            error_type=None,
            error_diagnostic="",
            elapsed_ms=1.0,
            schema_valid=True,
            graph_db_sha256=RepositoryGraphService.file_sha256(graph),
        ),
    )
    monkeypatch.setattr(
        RepositoryGraphService,
        "_graph_stats",
        staticmethod(
            lambda _graph: _GraphBuildStats(
                schema="v15.3-discovery-receipt",
                symbols=10,
                nodes={"Function": 10},
                edges={"CALLS": 1},
                files_attempted=10,
                files_parsed=10,
                file_hashes=10,
                parse_failures=0,
                file_hash_failures=0,
                files_discovered=12,
                skipped_count=1,
                discovery_method="git_ls_files",
                skipped_reasons={"unsupported_path": 1},
                skipped_paths=({"path": "README.txt", "reason": "unsupported_path"},),
                parse_failure_details=(),
                file_hash_failure_details=(),
                excluded_directories=(),
                receipt_complete=True,
            )
        ),
    )

    receipt = RepositoryGraphService(root, state_dir=state).build(force=True)
    assert receipt.build_status is GraphStatus.DEGRADED
    assert receipt.query_ready is False
    assert "discovery_accounting_mismatch" in receipt.degraded_reasons
