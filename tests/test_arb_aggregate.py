from __future__ import annotations

import json

from scripts.arb_aggregate import aggregate


def test_aggregate_reads_only_shard_files(tmp_path) -> None:
    (tmp_path / "arb-shard-0.jsonl").write_text(
        json.dumps(
            {
                "sample_id": "b",
                "abstained": True,
                "delivered_evidence": [],
                "ranked_candidates": [],
                "graph_status": "index_unavailable",
                "index_error_type": "MissingRuntime",
                "abstention_reason": "index_unavailable",
                "index_latency_ms": 2,
                "query_latency_ms": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "arb-shard-1.jsonl").write_text(
        json.dumps(
            {
                "sample_id": "a",
                "abstained": False,
                "delivered_evidence": [{"path": "src/a.py"}],
                "ranked_candidates": [{"path": "src/a.py"}],
                "graph_status": "source_backed",
                "index_error_type": None,
                "abstention_reason": None,
                "index_latency_ms": 4,
                "query_latency_ms": 3,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = aggregate(tmp_path, expected_rows=2)
    assert result["rows"] == 2
    assert result["complete"] is True
    assert result["delivered_rows"] == 1
    assert result["graph_status_counts"] == {"index_unavailable": 1, "source_backed": 1}


def test_aggregate_can_publish_partial_progress(tmp_path) -> None:
    (tmp_path / "arb-shard-0.jsonl").write_text(
        json.dumps({"sample_id": "only", "abstained": True}) + "\n",
        encoding="utf-8",
    )
    result = aggregate(tmp_path, expected_rows=2, allow_incomplete=True)
    assert result["complete"] is False
    assert result["rows"] == 1
