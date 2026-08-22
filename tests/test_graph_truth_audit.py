from __future__ import annotations

import json
from pathlib import Path

from scripts.graph_truth_audit import _metrics, _rust_group

ROOT = Path(__file__).resolve().parents[1]


def test_graph_truth_manifest_spans_claimed_languages_and_relationships() -> None:
    manifest = json.loads(
        (ROOT / "audit" / "graph_truth_facts.v1.json").read_text(encoding="utf-8")
    )

    assert manifest["schema"] == "gt.graph_truth_facts.v1"
    assert {fact["language"] for fact in manifest["facts"]} >= {
        "python",
        "javascript",
        "typescript",
        "go",
        "rust",
        "java",
    }
    assert {fact["relationship"] for fact in manifest["facts"]} >= {
        "callers",
        "callees",
        "imports",
        "reexports",
        "subclasses",
    }
    assert all(fact["oracle"]["kind"] for fact in manifest["facts"])


def test_truth_metrics_count_false_edges_and_missing_edges() -> None:
    rows = [
        {
            "true_positives": 3,
            "false_positives": 1,
            "false_negatives": 2,
            "query_supported": True,
            "wrong_file": 1,
            "wrong_symbol": 0,
            "exact_match": False,
        },
        {
            "true_positives": 2,
            "false_positives": 0,
            "false_negatives": 0,
            "query_supported": False,
            "wrong_file": 0,
            "wrong_symbol": 0,
            "exact_match": False,
        },
    ]

    metrics = _metrics(rows)

    assert metrics["precision"] == 0.833333
    assert metrics["recall"] == 0.714286
    assert metrics["false_positive_rate"] == 0.166667
    assert metrics["false_negative_rate"] == 0.285714
    assert metrics["unsupported_rate"] == 0.5
    assert metrics["exact_set_accuracy"] == 0.0
    assert metrics["stale_edge_rate"] == "NOT_MEASURED_IN_STATIC_TRUTH_CORPUS"


def test_rust_use_oracle_expands_nested_crate_group() -> None:
    tokens = [
        "escape",
        "::",
        "{",
        "escape",
        ",",
        "unescape",
        "}",
        ",",
        "hostname",
        "::",
        "hostname",
        "}",
    ]

    paths, consumed = _rust_group(tokens, 0, [])

    assert consumed == len(tokens)
    assert paths == [
        ["escape", "escape"],
        ["escape", "unescape"],
        ["hostname", "hostname"],
    ]
