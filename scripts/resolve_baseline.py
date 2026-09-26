"""Resolve the GT-off comparator for a launch-time model, without running GT-off.

The model is chosen when a run is launched, so the comparator must be found,
not assumed. Source: the public DeepSWE leaderboard trial table (one row per
trial, with model, harness and reasoning effort). A comparator exists only
when model AND reasoning effort match; otherwise the result says so and why,
and the run reports the push-vs-attached A/B alone.

Model matching is exact after normalization (provider prefix dropped, case
and dots folded). A trailing date pin (``-0731``) may be stripped, but that
match is labelled ``date_suffix_stripped`` because the leaderboard row does
not record which dated snapshot served it.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_TRIALS_URL = "https://deepswe.datacurve.ai/artifacts/v1.1/trials.json"
_DATE_SUFFIX = re.compile(r"-\d{4}$")
_Z95 = 1.959963984540054


def normalize_model(model: str) -> str:
    name = model.strip().lower().split("/")[-1]
    return name.replace(".", "-").replace("_", "-")


def load_trials(source: str) -> list[dict[str, Any]]:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=120) as response:  # noqa: S310 - fixed public artifact
            document = json.loads(response.read().decode("utf-8"))
    else:
        document = json.loads(Path(source).read_text(encoding="utf-8"))
    rows = document.get("rows") if isinstance(document, dict) else document
    if not isinstance(rows, list):
        raise ValueError("trials_document_shape_invalid")
    return [row for row in rows if isinstance(row, dict)]


def _match(rows: list[dict[str, Any]], model: str) -> tuple[str, str] | None:
    available = {str(row.get("model") or "") for row in rows}
    wanted = normalize_model(model)
    if wanted in available:
        return wanted, "exact"
    stripped = _DATE_SUFFIX.sub("", wanted)
    if stripped != wanted and stripped in available:
        return stripped, "date_suffix_stripped"
    return None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row.get("included_in_score") is False:
            continue
        by_task[str(row.get("task_name"))].append(1.0 if row.get("passed") else 0.0)
    rates = [sum(values) / len(values) for values in by_task.values() if values]
    n_tasks = len(rates)
    n_trials = sum(len(values) for values in by_task.values())
    passes = int(sum(sum(values) for values in by_task.values()))
    mean = sum(rates) / n_tasks if n_tasks else 0.0
    if n_tasks > 1:
        variance = sum((rate - mean) ** 2 for rate in rates) / (n_tasks - 1)
        half = _Z95 * math.sqrt(variance / n_tasks)
    else:
        half = 0.0
    runs = [len(values) for values in by_task.values()]
    return {
        "n_tasks": n_tasks,
        "n_trials": n_trials,
        "passes": passes,
        "pass_at_1": round(mean, 4),
        "ci95": [round(max(0.0, mean - half), 4), round(min(1.0, mean + half), 4)],
        "ci_method": "task_clustered_normal",
        "runs_per_task": sorted(set(runs)),
        "per_task_pass_rate": {task: round(sum(v) / len(v), 4)
                               for task, v in sorted(by_task.items())},
        "mean_agent_steps": round(
            sum(float(row.get("n_agent_steps") or 0) for row in rows) / len(rows), 1
        ) if rows else 0.0,
    }


def resolve(
    rows: list[dict[str, Any]],
    *,
    model: str,
    reasoning_effort: str,
    harness: str = "mini-swe-agent",
    tasks: list[str] | None = None,
) -> dict[str, Any]:
    matched = _match(rows, model)
    requested = {"model": model, "reasoning_effort": reasoning_effort or "unset",
                 "harness": harness}
    if matched is None:
        return {"comparator": None, "reason": "model_not_on_leaderboard", "requested": requested}
    name, quality = matched
    candidates = [row for row in rows if row.get("model") == name
                  and str(row.get("harness") or "") == harness]
    if not candidates:
        return {"comparator": None, "reason": "harness_not_on_leaderboard", "requested": requested}
    efforts = sorted({str(row.get("reasoning_effort") or "unset") for row in candidates})
    effort = (reasoning_effort or "unset").lower()
    selected = [row for row in candidates if str(row.get("reasoning_effort") or "unset") == effort]
    if not selected:
        return {"comparator": None, "reason": "reasoning_effort_mismatch",
                "requested": requested, "leaderboard_efforts": efforts}
    if tasks:
        wanted = set(tasks)
        selected = [row for row in selected if row.get("task_name") in wanted]
        missing = sorted(wanted - {str(row.get("task_name")) for row in selected})
    else:
        missing = []
    return {
        "comparator": {
            "source": "deepswe_v1.1_leaderboard_trials",
            "leaderboard_model": name,
            "match": quality,
            "reasoning_effort": effort,
            "harness": harness,
            **summarize(selected),
            "missing_tasks": missing,
        },
        "requested": requested,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning-effort", default="")
    parser.add_argument("--harness", default="mini-swe-agent")
    parser.add_argument("--trials", default=DEFAULT_TRIALS_URL,
                        help="trials.json path or URL (default: the public v1.1 artifact)")
    parser.add_argument("--tasks", default="", help="comma list restricting the task set")
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)
    tasks = [task.strip() for task in args.tasks.split(",") if task.strip()]
    result = resolve(load_trials(args.trials), model=args.model,
                     reasoning_effort=args.reasoning_effort, harness=args.harness,
                     tasks=tasks or None)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text if not args.output else json.dumps(
        {key: value for key, value in (result.get("comparator") or {}).items()
         if key != "per_task_pass_rate"} or result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
