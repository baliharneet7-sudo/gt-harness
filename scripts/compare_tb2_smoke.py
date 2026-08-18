"""Compare a current TB2 smoke result with offline GT-off and previous GT-on data.

The task set is supplied by a caller-owned manifest.  This script never selects
tasks, runs an agent, or treats missing baseline instrumentation as zero.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


METRICS = (
    "provider_calls",
    "executor_provider_calls",
    "bootstrap_provider_calls",
    "assistant_steps",
    "actions",
    "effective_task_actions",
    "actual_environment_execs",
    "check_actions",
    "workspace_change_actions",
    "input_tokens",
    "output_tokens",
    "cache_tokens",
    "uncached_input_tokens",
    "total_tokens",
    "normalized_cost_usd",
    "repository_mirror_transfer_ms",
    "repository_index_refresh_ms",
    "provider_delivery_count",
    "provider_delivery_visible_chars",
    "preemptive_retrieval_deliveries",
    "preemptive_retrieval_chars_added",
)

ALIASES = {
    "provider_calls": ("provider_calls", "api_calls"),
    "executor_provider_calls": ("executor_provider_calls", "executor_api_calls"),
    "bootstrap_provider_calls": ("bootstrap_provider_calls",),
}


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(float(value)) else None


def _task_from_trial(row: dict[str, Any]) -> str:
    return str(row.get("task") or row.get("task_name") or "").split("__", 1)[0]


def _outcomes(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    direct = payload.get("rows")
    if isinstance(direct, list):
        return {
            str(row["task"]): row
            for row in direct
            if isinstance(row, dict) and isinstance(row.get("task"), str)
        }
    result: dict[str, dict[str, Any]] = {}
    for row in payload.get("trial_results") or ():
        if not isinstance(row, dict):
            continue
        task = _task_from_trial(row)
        if not task:
            continue
        rewards = (row.get("verifier_result") or {}).get("rewards") or {}
        values = [value for value in rewards.values() if _number(value) is not None]
        result[task] = {
            "task": task,
            "solved": bool(values) and all(float(value) >= 1.0 for value in values),
            "reward": 1.0 if values and all(float(value) >= 1.0 for value in values) else 0.0,
            "censored": bool((row.get("agent_result") or {}).get("metadata", {}).get("censored", False)),
        }
    return result


def _metrics(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = payload.get("receipt_metrics")
    if isinstance(rows, list):
        return {
            str(row["task"]): row
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("task"), str)
        }
    direct = payload.get("rows")
    if isinstance(direct, list):
        return {
            str(row["task"]): row
            for row in direct
            if isinstance(row, dict) and isinstance(row.get("task"), str)
        }
    return {}


def _metric(row: dict[str, Any] | None, name: str) -> int | float | None:
    if not row:
        return None
    if isinstance(row.get("metrics"), dict):
        row = row["metrics"]
    for key in ALIASES.get(name, (name,)):
        value = _number(row.get(key))
        if value is not None:
            return value
    return None


def _delta(after: dict[str, Any] | None, before: dict[str, Any] | None, name: str) -> int | float | None:
    left = _metric(after, name)
    right = _metric(before, name)
    if left is None or right is None:
        return None
    return left - right


def _aggregate(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    output: dict[str, Any] = {"arm": arm, "task_count": len(rows)}
    solved = [row for row in rows if (row.get(arm) or {}).get("solved") is True]
    output["solved"] = len(solved)
    output["resolve_rate"] = len(solved) / len(rows) if rows else None
    for name in METRICS:
        values = [_metric(row.get(arm), name) for row in rows]
        numeric = [value for value in values if value is not None]
        output[name] = sum(numeric) if len(numeric) == len(rows) and rows else None
    return output


def compare(*, manifest: dict[str, Any], baseline: dict[str, Any], previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks or any(not isinstance(task, str) or not task for task in tasks):
        raise ValueError("manifest tasks must be a non-empty list of task names")
    if len(set(tasks)) != len(tasks):
        raise ValueError("manifest task list contains duplicates")

    arms = {
        "gt_off": (_outcomes(baseline), _metrics(baseline)),
        "previous_gt": (_outcomes(previous), _metrics(previous)),
        "current_gt": (_outcomes(current), _metrics(current)),
    }
    rows: list[dict[str, Any]] = []
    for task in tasks:
        entry: dict[str, Any] = {"task": task}
        for arm, (outcomes, metrics) in arms.items():
            outcome = outcomes.get(task)
            entry[arm] = {
                "solved": outcome.get("solved") if outcome else None,
                "reward": outcome.get("reward") if outcome else None,
                "censored": outcome.get("censored") if outcome else None,
                "metrics": {name: _metric(metrics.get(task), name) for name in METRICS},
            }
        entry["current_minus_gt_off"] = {
            name: _delta(entry["current_gt"]["metrics"], entry["gt_off"]["metrics"], name)
            for name in METRICS
        }
        entry["current_minus_previous_gt"] = {
            name: _delta(entry["current_gt"]["metrics"], entry["previous_gt"]["metrics"], name)
            for name in METRICS
        }
        rows.append(entry)

    def solved_set(arm: str) -> set[str]:
        return {row["task"] for row in rows if row[arm]["solved"] is True}

    sets = {arm: solved_set(arm) for arm in arms}
    flip_sets = {
        "current_vs_gt_off_positive": sorted(sets["current_gt"] - sets["gt_off"]),
        "current_vs_gt_off_negative": sorted(sets["gt_off"] - sets["current_gt"]),
        "current_vs_previous_gt_positive": sorted(sets["current_gt"] - sets["previous_gt"]),
        "current_vs_previous_gt_negative": sorted(sets["previous_gt"] - sets["current_gt"]),
    }
    return {
        "schema": "gt.tb2.smoke_comparison.v1",
        "manifest": manifest,
        "arms": {
            arm: _aggregate(rows, arm)
            for arm in arms
        },
        "flips": flip_sets,
        "rows": rows,
        "missing_metrics": {
            arm: sorted({name for row in rows for name, value in row[arm]["metrics"].items() if value is None})
            for arm in arms
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# TB2 regression smoke comparison",
        "",
        "Task selection is caller-owned and comes from the recorded smoke manifest.",
        "",
        "| Arm | Solved | Tasks | Resolve rate | Provider calls | Assistant steps | Total tokens | Uncached input | Cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm, label in (("gt_off", "GT off"), ("previous_gt", "Previous GT"), ("current_gt", "Current GT")):
        row = report["arms"][arm]
        def show(name: str) -> str:
            value = row.get(name)
            return "-" if value is None else str(value)
        lines.append(
            f"| {label} | {show('solved')} | {show('task_count')} | {show('resolve_rate')} | "
            f"{show('provider_calls')} | {show('assistant_steps')} | {show('total_tokens')} | "
            f"{show('uncached_input_tokens')} | {show('normalized_cost_usd')} |"
        )
    lines += ["", "## Solve flips", ""]
    for name, values in report["flips"].items():
        lines.append(f"- {name}: {', '.join(values) or 'none'}")
    lines += ["", "## Per-task resource deltas", "", "| Task | Current vs GT off tokens | Current vs previous tokens | Current steps | Current calls |", "|---|---:|---:|---:|---:|"]
    for row in report["rows"]:
        current = row["current_gt"]["metrics"]
        lines.append(
            f"| {row['task']} | {row['current_minus_gt_off']['total_tokens'] or '-'} | "
            f"{row['current_minus_previous_gt']['total_tokens'] or '-'} | "
            f"{current['assistant_steps'] or '-'} | {current['provider_calls'] or '-'} |"
        )
    lines += ["", "Missing values are reported as `-`; they are not treated as zero.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--previous-gt", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare(
        manifest=json.loads(args.manifest.read_text(encoding="utf-8")),
        baseline=json.loads(args.baseline.read_text(encoding="utf-8")),
        previous=json.loads(args.previous_gt.read_text(encoding="utf-8")),
        current=json.loads(args.current.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "tasks": len(report["rows"]), "flips": report["flips"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
