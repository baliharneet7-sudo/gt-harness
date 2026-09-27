"""Per-task feature observability for attached delivery.

Every feature a task could have seen is answerable from the task's own
journal and report, without the graph or the trajectory:

* ``gt_feature_inventory`` (journal, once per graph): how much data the
  repository's graph holds for each of the 21 features. Zero means the
  feature had nothing to say in this repository (NOT_IN_REPO), not that it
  failed.
* ``features=[...]`` on every ``gt_augment`` / ``gt_action_augment`` hit and
  on ``attached_plan_built``: exactly which features that delivery carried.
* ``gt_delivery.features_reached`` / ``feature_inventory`` in the task report
  (and the benchmark progress receipt): the per-task matrix row.

So a feature that did not reach the agent is always classifiable as
"repo had none", "agent never triggered it", or "had data and a trigger but
was not delivered" (a defect) - live, from small artifacts.
"""
from __future__ import annotations

import sqlite3
from typing import Any

# Feature -> the graph data it reports. The queries count the producer's own
# tables; a missing table counts as zero.
INVENTORY_QUERIES: dict[str, str] = {
    "F2": "SELECT COUNT(*) FROM nodes WHERE label IN ('Function','Method','Class','Interface')",
    "F3": "SELECT COUNT(*) FROM edges WHERE type IN ('CALLS','ACCESSES','READS','WRITES','INJECTS','IMPORTS')",
    "F4": "SELECT COUNT(*) FROM edges WHERE type = 'CALLS'",
    "F5": "SELECT COUNT(*) FROM edges WHERE type = 'CALLS' AND resolution_method IN "
          "('same_file','import','import_type','verified_unique','lsp','lsp_verified')",
    "F6": "SELECT COUNT(*) FROM edges WHERE type = 'CALLS' AND resolution_method = 'callable_value'",
    "F7": "SELECT COUNT(*) FROM edges WHERE type IN ('OVERRIDES','METHOD_OVERRIDES','EXTENDS','IMPLEMENTS',"
          "'DECLARED_IMPLEMENTS') OR (type = 'CALLS' AND resolution_method IN "
          "('type_flow','inherited','return_type','impl_method','unique_method'))",
    "F8": "SELECT COUNT(*) FROM edges WHERE type IN ('HANDLES_ROUTE','MIDDLEWARE_ON','INJECTS')",
    "F9": "SELECT COUNT(*) FROM processes",
    "F10": "SELECT COUNT(*) FROM communities",
    "F11": "SELECT COUNT(*) FROM nodes",
    "F12": "SELECT COUNT(*) FROM nodes WHERE label IN ('Function','Method','Class')",
    "F13": "SELECT (SELECT COUNT(*) FROM edges WHERE type = 'CALLS') + (SELECT COUNT(*) FROM cochanges)",
    "F14": "SELECT COUNT(*) FROM nodes WHERE label IN ('Function','Method')",
    "F15": "SELECT COUNT(*) FROM properties WHERE kind = 'data_flow'",
    "F16": "SELECT COUNT(*) FROM nodes WHERE label IN ('Function','Method')",
    "F17": "SELECT COUNT(*) FROM nodes WHERE label IN ('Function','Method')",
    "F18": "SELECT COUNT(*) FROM edges WHERE type IN ('HANDLES_ROUTE','API_CALL')",
    "F19": "SELECT COUNT(*) FROM edges WHERE type = 'CALLS'",
    "F20": "SELECT COUNT(*) FROM nodes WHERE is_test = 1",
}
# Always present when a graph exists: parsing and freshness are the substrate.
SUBSTRATE = ("F1", "F21")


def inventory(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for feature, sql in INVENTORY_QUERIES.items():
        try:
            counts[feature] = int(conn.execute(sql).fetchone()[0] or 0)
        except sqlite3.Error:
            counts[feature] = 0
    for feature in SUBSTRATE:
        counts[feature] = 1 if counts.get("F2", 0) else 0
    return dict(sorted(counts.items(), key=lambda item: int(item[0][1:])))


def merge(*maps: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for mapping in maps:
        items = mapping.items() if isinstance(mapping, dict) else ((f, 1) for f in mapping or ())
        for feature, count in items:
            out[feature] = out.get(feature, 0) + int(count or 0)
    return dict(sorted(out.items(), key=lambda item: int(item[0][1:])))


__all__ = ["INVENTORY_QUERIES", "inventory", "merge"]
