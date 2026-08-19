"""Audit a matched process-on/process-off pair without calling a provider.

This deliberately measures delivery and trajectory alignment only.  A paired
run can support a causal claim only when the task set, repository revisions,
model/scaffold/settings, and evaluation are matched; this script therefore
emits those requirements explicitly and never labels alignment as causality.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _task_name(path: Path) -> str:
    for parent in path.parents:
        if "-task-" in parent.name:
            return parent.name.split("-task-", 1)[1]
    return path.parent.name


def _receipts(root: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("central_receipt.json")):
        task = _task_name(path)
        if task in rows:
            raise ValueError(f"duplicate task {task!r} below {root}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"receipt is not an object: {path}")
        rows[task] = value
    if not rows:
        raise ValueError(f"no central receipts below {root}")
    return rows


def _surface(receipt: dict[str, Any]) -> dict[str, Any]:
    runtime = receipt.get("repository_context") or {}
    deliveries = tuple(runtime.get("deliveries") or ())
    decisions = tuple(runtime.get("decisions") or ())
    execution_views = sum(
        len((row.get("projection") or {}).get("execution_views") or ())
        for row in deliveries
        if isinstance(row, dict)
    )
    coverage = [
        (row.get("projection") or {}).get("process_coverage") or {}
        for row in deliveries
        if isinstance(row, dict)
    ]
    utilization = runtime.get("utilization") or {}
    return {
        "enabled": runtime.get("enabled") is True,
        "opportunities": len(decisions),
        "deliveries": len(deliveries),
        "execution_views": execution_views,
        "coverage_profiles": sorted(
            {
                str(item.get("profile_id") or "")
                for item in coverage
                if isinstance(item, dict) and item.get("profile_id")
            }
        ),
        "replacement_opportunities": int(
            utilization.get("replacement_opportunities") or 0
        ),
        "causal_claim_allowed": utilization.get("causal_claim_allowed") is True,
    }


def compare(on_root: Path, off_root: Path) -> dict[str, Any]:
    on, off = _receipts(on_root), _receipts(off_root)
    tasks = sorted(set(on) | set(off))
    rows: dict[str, Any] = {}
    for task in tasks:
        if task not in on or task not in off:
            rows[task] = {
                "matched": False,
                "missing_on": task not in on,
                "missing_off": task not in off,
            }
            continue
        rows[task] = {
            "matched": True,
            "process_on": _surface(on[task]),
            "process_off": _surface(off[task]),
        }
    matched = [row for row in rows.values() if row.get("matched")]
    return {
        "schema": "gt.central_process_ablation.v1",
        "process_on_root": str(on_root),
        "process_off_root": str(off_root),
        "task_count": len(tasks),
        "matched_task_count": len(matched),
        "all_tasks_matched": len(matched) == len(tasks),
        "causal_claim_allowed": False,
        "causal_claim_requires": [
            "same_task_and_repository_revisions",
            "same_model_scaffold_settings_and_budget",
            "same_evaluation_and_trial_protocol",
            "complete_provider_delivery_and_trajectory_receipts",
        ],
        "tasks": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("process_on_root", type=Path)
    parser.add_argument("process_off_root", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    report = compare(args.process_on_root.resolve(), args.process_off_root.resolve())
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.json:
        args.json.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["all_tasks_matched"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
