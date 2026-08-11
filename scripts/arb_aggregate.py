#!/usr/bin/env python3
"""Aggregate lossless ARB GT shard receipts without gold or task heuristics."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def aggregate(
    root: str | Path,
    *,
    expected_rows: int | None = None,
    expected_samples: str | Path | None = None,
    allow_incomplete: bool = False,
) -> dict[str, Any]:
    root_path = Path(root)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    shard_paths = sorted(root_path.rglob("arb-shard-*.jsonl"))
    shard_rows: dict[str, int] = {}
    for path in shard_paths:
        shard_rows[path.name] = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            sample_id = str(row.get("sample_id") or "")
            if not sample_id:
                raise ValueError(f"missing sample_id in {path}")
            if sample_id in seen:
                raise ValueError(f"duplicate sample_id: {sample_id}")
            seen.add(sample_id)
            rows.append(row)
            shard_rows[path.name] += 1
    rows.sort(key=lambda row: str(row["sample_id"]))
    complete = expected_rows is None or len(rows) == expected_rows
    if expected_rows is not None and not complete and not allow_incomplete:
        raise ValueError(f"expected {expected_rows} rows, found {len(rows)}")
    delivered = sum(bool(row.get("delivered_evidence")) for row in rows)
    diagnostics = Counter(str(row.get("index_error_type") or "") for row in rows)
    statuses = Counter(str(row.get("graph_status") or "") for row in rows)
    reasons = Counter(str(row.get("abstention_reason") or "") for row in rows)
    expected_ids: set[str] = set()
    if expected_samples:
        expected_path = Path(expected_samples)
        for line in expected_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                expected_ids.add(str(json.loads(line).get("sample_id") or ""))
        expected_ids.discard("")
        if expected_ids and len(rows) != len(expected_ids) and not allow_incomplete:
            raise ValueError(f"expected {len(expected_ids)} sample ids, found {len(rows)}")
    missing_ids = sorted(expected_ids - seen) if expected_ids else []
    extra_ids = sorted(seen - expected_ids) if expected_ids else []
    if extra_ids:
        # Extra IDs mean the shard set is not the declared benchmark population.
        # Unlike missing rows, this is never valid partial progress.
        raise ValueError(f"extra sample ids: {extra_ids[:5]}")
    if expected_ids:
        complete = not missing_ids
    return {
        "schema": "gt.arb.aggregate.v1",
        "rows": len(rows),
        "expected_rows": expected_rows,
        "complete": complete,
        "shards_seen": len(shard_paths),
        "shard_rows": shard_rows,
        "missing_sample_ids": missing_ids,
        "extra_sample_ids": extra_ids,
        "delivered_rows": delivered,
        "abstained_rows": sum(bool(row.get("abstained")) for row in rows),
        "ranked_candidate_rows": sum(bool(row.get("ranked_candidates")) for row in rows),
        "graph_status_counts": dict(sorted(statuses.items())),
        "index_error_type_counts": dict(sorted(diagnostics.items())),
        "abstention_reason_counts": dict(sorted(reasons.items())),
        "mean_index_latency_ms": round(
            sum(float(row.get("index_latency_ms") or 0.0) for row in rows) / len(rows), 6
        ) if rows else 0.0,
        "mean_query_latency_ms": round(
            sum(float(row.get("query_latency_ms") or 0.0) for row in rows) / len(rows), 6
        ) if rows else 0.0,
        "index_cache_hits": sum(bool(row.get("index_cache_hit")) for row in rows),
        "repository_cache_hits": sum(
            bool(row.get("repository_cache_hit")) for row in rows
        ),
        "rows_detail": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--expected-rows", type=int)
    parser.add_argument("--expected-samples", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = aggregate(
        args.root,
        expected_rows=args.expected_rows,
        expected_samples=args.expected_samples,
        allow_incomplete=args.allow_incomplete,
    )
    Path(args.output).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
