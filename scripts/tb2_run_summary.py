#!/usr/bin/env python3
"""Render a TB2 GT run as Markdown, against the cohort it must be read against.

A run of 89 tasks produces 89 job pages and one JSON artifact, and neither
answers the question actually being asked while it runs: which tasks are done,
which are still out, and is this better or worse than the GT-off baseline. The
counts alone cannot answer the last one - a run that scores 66 by solving a
different 66 is not the same result - so every table here is per task and
carries the baseline's own reward beside ours.

Two modes, because the run has two moments:

``task``  one job, as it finishes: what it scored and what GT did to get there.
``run``   the whole cohort, from the aggregated receipts: regressions first.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# A task's outcome, in the one column a reader scans first.
_MARK = {
    "passed": "PASS",
    "verifier_failed": "FAIL",
    "infrastructure_failed": "INFRA",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _reward_text(reward: Any) -> str:
    if reward is None:
        return "-"
    if isinstance(reward, (int, float)):
        return f"{float(reward):g}"
    return str(reward)


def _delta(ours: Any, baseline: Any) -> str:
    """Name the four cases plainly; a blank cell hides the ones that matter."""
    if baseline is None:
        return "no baseline"
    if ours is None:
        return "not graded"
    if ours == baseline:
        return "same"
    return "REGRESSION" if baseline > ours else "gain"


def render_task(
    progress: dict[str, Any],
    *,
    receipt: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    baseline_rewards: dict[str, Any] | None = None,
) -> str:
    rows = progress.get("tasks") or []
    if not rows:
        return "### TB2 task\n\nNo progress receipt was written.\n"
    task = rows[0]
    task_id = str(task.get("task_id") or "?")
    baseline = (baseline_rewards or {}).get(task_id)
    state = str(task.get("state") or "?")

    lines = [
        f"### {task_id} - {_MARK.get(state, state)}",
        "",
        "| reward | baseline | verdict | class | error |",
        "|---|---|---|---|---|",
        f"| {_reward_text(task.get('reward'))} | {_reward_text(baseline)} "
        f"| {_delta(task.get('reward'), baseline)} | {task.get('failure_class') or '-'} "
        f"| {task.get('error_code') or '-'} |",
        "",
    ]

    if receipt:
        inp = int(receipt.get("input_tokens") or 0)
        cached = int(receipt.get("cached_tokens") or 0)
        share = f"{cached / inp:.1%}" if inp else "-"
        lines += [
            "| input tok | cached | output tok | cost |",
            "|---|---|---|---|",
            f"| {inp:,} | {share} | {int(receipt.get('output_tokens') or 0):,} "
            f"| ${float(receipt.get('total_cost') or 0):.3f} |",
            "",
        ]
    else:
        # The run was cut off before it sealed one. Say so here rather than
        # leaving a reader to infer it from an absent table.
        lines += ["_No `gt-run.json`: the run did not seal a product receipt._", ""]

    if events is not None:
        counted = {
            "graph recoveries": sum(e.get("event") == "graph_recovery" for e in events),
            "recovery suspended": sum(
                e.get("event") == "graph_recovery_suspended" for e in events
            ),
            "graph unavailable": sum(
                "benchmark_graph_unavailable" in str(e.get("reason") or "")
                or e.get("event") == "index_unavailable"
                for e in events
            ),
            "submissions refused": sum(
                e.get("event") == "action_suppressed"
                and e.get("reason") == "submit_refused"
                for e in events
            ),
        }
        named = ", ".join(f"{name}: {count}" for name, count in counted.items())
        lines += [f"GT: {named}", ""]
    return "\n".join(lines)


def render_run(summary: dict[str, Any], cohort: dict[str, Any] | None = None) -> str:
    baseline_rewards = (cohort or {}).get("baseline_rewards") or {}
    rows = summary.get("tasks") or []
    by_id = {str(row.get("task_id")): row for row in rows}
    expected = sorted(by_id)

    scored = [
        (task_id, by_id[task_id].get("reward"), baseline_rewards.get(task_id))
        for task_id in expected
    ]
    regressions = [row for row in scored if _delta(row[1], row[2]) == "REGRESSION"]
    gains = [row for row in scored if _delta(row[1], row[2]) == "gain"]

    total = int(summary.get("total") or len(expected))
    completed = int(summary.get("completed") or 0)
    solved = int(summary.get("passed") or 0)
    # Only the tasks this run actually reported: comparing our 88 against the
    # baseline's 89 would hand us a task we never ran.
    comparable = sum(1 for *_head, base in scored if base == 1.0)

    lines = [
        "## TB2 GT run",
        "",
        f"- graded **{summary.get('officially_graded', 0)}** of {total}"
        f" (completed {completed}, remaining {total - completed})",
        f"- solved **{solved}** - baseline solved **{comparable}** of the same tasks",
        f"- regressions **{len(regressions)}**, gains **{len(gains)}**",
        f"- infrastructure failures {summary.get('infrastructure_failed', 0)}",
    ]
    excluded = summary.get("excluded") or []
    if excluded:
        named = ", ".join(f"{row['task']} ({row['reason']})" for row in excluded)
        lines.append(f"- excluded {len(excluded)}: {named}")
    lines += ["", "| task | reward | baseline | verdict | class |", "|---|---|---|---|---|"]

    # Regressions first: the rows that decide whether this run was a step back
    # should not be found by scrolling.
    ordering = sorted(
        expected,
        key=lambda task_id: (
            {"REGRESSION": 0, "not graded": 1, "gain": 2}.get(
                _delta(by_id[task_id].get("reward"), baseline_rewards.get(task_id)), 3
            ),
            task_id,
        ),
    )
    for task_id in ordering:
        row = by_id[task_id]
        lines.append(
            f"| {task_id} | {_reward_text(row.get('reward'))} "
            f"| {_reward_text(baseline_rewards.get(task_id))} "
            f"| {_delta(row.get('reward'), baseline_rewards.get(task_id))} "
            f"| {row.get('failure_class') or '-'} |"
        )
    return "\n".join(lines) + "\n"


def _read_events(path: Path | None) -> list[dict[str, Any]] | None:
    if path is None or not path.is_file():
        return None
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    one = sub.add_parser("task")
    one.add_argument("--progress", type=Path, required=True)
    one.add_argument("--receipt", type=Path)
    one.add_argument("--events", type=Path)
    one.add_argument("--cohort", type=Path)
    one.add_argument("--output", type=Path)

    whole = sub.add_parser("run")
    whole.add_argument("--summary", type=Path, required=True)
    whole.add_argument("--cohort", type=Path)
    whole.add_argument("--output", type=Path)

    args = parser.parse_args(argv)
    cohort = _load(args.cohort) if args.cohort and args.cohort.is_file() else None

    if args.mode == "task":
        receipt = (
            _load(args.receipt) if args.receipt and args.receipt.is_file() else None
        )
        text = render_task(
            _load(args.progress),
            receipt=receipt,
            events=_read_events(args.events),
            baseline_rewards=(cohort or {}).get("baseline_rewards"),
        )
    else:
        text = render_run(_load(args.summary), cohort)

    if args.output:
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
