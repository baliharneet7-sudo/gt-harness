from __future__ import annotations

from pathlib import Path

from gt_engine.bridge import GTBridge
from gt_engine.indexer import IndexBuildReceipt, IndexBuildStatus


def _wake(bridge: GTBridge, root: Path) -> None:
    source = root / "newmod.py"
    content = "def fresh_fn(value):\n    return value * 2\n"
    source.write_text(content, encoding="utf-8")
    bridge.enrich(
        "edit_file",
        {"path": str(source)},
        "edited",
        False,
        edit_before=None,
        edit_after=content,
    )


def _refresh_rows(bridge: GTBridge) -> list[dict]:
    return [
        row
        for row in bridge._attribution.rows
        if row["event_type"].startswith("graph.context_refresh")
    ]


def test_graph_wake_failure_receipts_exact_index_cause(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GT_L6_FRESH", "1")
    attempts = 0

    def fail_index(*_args, **_kwargs) -> IndexBuildReceipt:
        nonlocal attempts
        attempts += 1
        return IndexBuildReceipt(
            status=IndexBuildStatus.BUILD_FAILED,
            binary_sha256="a" * 64,
            elapsed_ms=12.5,
            error_type="parser_failure",
            error_diagnostic="source parser rejected input",
            source_files=1,
            indexable_files=1,
            parser_failures=1,
        )

    monkeypatch.setattr(
        "gt_engine.indexer.ensure_index_with_receipt",
        fail_index,
    )
    bridge = GTBridge(str(tmp_path))

    _wake(bridge, tmp_path)

    assert attempts == 1
    assert bridge.graph_db is None
    failure = next(
        row for row in _refresh_rows(bridge) if row["event_type"].endswith("failed")
    )
    assert failure["payload"]["reason"] == "index_build_failed"
    assert failure["payload"]["index_attempts"] == 1
    receipt = failure["payload"]["index_receipts"][0]
    assert receipt["status"] == "build_failed"
    assert receipt["error_type"] == "parser_failure"
    assert receipt["error_diagnostic"] == "source parser rejected input"
    assert receipt["binary_sha256"] == "a" * 64
    assert receipt["parser_failures"] == 1


def test_graph_refresh_failure_invalidates_pre_edit_graph_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GT_L6_FRESH", "1")
    stale_graph = tmp_path / "stale.db"
    stale_graph.write_bytes(b"stale")
    monkeypatch.setattr(
        "gt_engine.indexer.ensure_index_with_receipt",
        lambda *_args, **_kwargs: IndexBuildReceipt(
            status=IndexBuildStatus.BUILD_FAILED,
            error_type="parser_failure",
            error_diagnostic="new source could not be indexed",
            source_files=1,
            indexable_files=1,
            parser_failures=1,
        ),
    )
    bridge = GTBridge(str(tmp_path), graph_db=str(stale_graph))
    bridge._graph_projection = object()
    bridge._evidence_router = object()
    bridge._graph_evidence = (object(),)

    _wake(bridge, tmp_path)

    assert bridge.graph_db is None
    assert bridge._graph_projection is None
    assert bridge._evidence_router is None
    assert bridge._graph_evidence == ()


def test_graph_wake_retries_one_classified_transient_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GT_L6_FRESH", "1")
    graph = tmp_path / "fresh-graph.db"
    graph.write_bytes(b"graph")
    receipts = iter(
        (
            IndexBuildReceipt(
                status=IndexBuildStatus.BUILD_FAILED,
                binary_sha256="b" * 64,
                error_type="PermissionError",
                error_diagnostic="sharing violation while replacing graph",
                source_files=1,
                indexable_files=1,
            ),
            IndexBuildReceipt(
                status=IndexBuildStatus.AVAILABLE,
                graph_db=str(graph),
                graph_revision="revision-2",
                binary_sha256="b" * 64,
                source_files=1,
                indexable_files=1,
                schema_valid=True,
                node_count=1,
            ),
        )
    )
    monkeypatch.setattr(
        "gt_engine.indexer.ensure_index_with_receipt",
        lambda *_args, **_kwargs: next(receipts),
    )
    bridge = GTBridge(str(tmp_path))

    _wake(bridge, tmp_path)

    assert bridge.graph_db == str(graph)
    refreshed = next(
        row
        for row in _refresh_rows(bridge)
        if row["event_type"] == "graph.context_refreshed"
    )
    assert refreshed["payload"]["index_attempts"] == 2
    assert [
        receipt["status"] for receipt in refreshed["payload"]["index_receipts"]
    ] == ["build_failed", "available"]
    assert refreshed["payload"]["transient_retry"] is True
