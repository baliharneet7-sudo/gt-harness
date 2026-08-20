#!/usr/bin/env python3
"""Canonical Harbor result ingestion for aggregate and per-trial schemas."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _task_name(row: dict[str, Any]) -> str:
    value = str(row.get("task_name") or row.get("trial_name") or "").strip()
    if "__" in value and not row.get("task_name"):
        value = value.split("__", 1)[0]
    return value.rstrip("/").rsplit("/", 1)[-1]


def _solved(row: dict[str, Any]) -> bool:
    rewards = (row.get("verifier_result") or {}).get("rewards") or {}
    values = [
        value
        for value in rewards.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return bool(values) and all(value >= 1 for value in values)


def _rows(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    aggregate = payload.get("trial_results")
    if isinstance(aggregate, list):
        return tuple(row for row in aggregate if isinstance(row, dict))
    if payload.get("task_name") or payload.get("verifier_result") or payload.get("exception_info"):
        return (payload,)
    return ()


@dataclass(frozen=True, slots=True)
class HarborResultCollection:
    trials: tuple[dict[str, Any], ...]
    expected_tasks: tuple[str, ...]
    missing_tasks: tuple[str, ...]
    unexpected_tasks: tuple[str, ...]
    solved_tasks: tuple[str, ...]
    errored_tasks: tuple[str, ...]
    failures: tuple[str, ...]
    result_files: int
    ignored_job_results: int
    duplicate_identical_rows: int
    per_shard: tuple[tuple[str, int], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "gt.harbor_result_collection.v1",
            "expected_tasks": list(self.expected_tasks),
            "missing_tasks": list(self.missing_tasks),
            "unexpected_tasks": list(self.unexpected_tasks),
            "n_trials": len(self.trials),
            "n_graded": sum(
                bool((row.get("verifier_result") or {}).get("rewards"))
                for row in self.trials
            ),
            "n_errored": len(self.errored_tasks),
            "n_solved": len(self.solved_tasks),
            "solved_tasks": list(self.solved_tasks),
            "errored_tasks": list(self.errored_tasks),
            "failures": list(self.failures),
            "result_files": self.result_files,
            "ignored_job_results": self.ignored_job_results,
            "duplicate_identical_rows": self.duplicate_identical_rows,
            "per_shard": [
                {"shard": shard, "trials": count} for shard, count in self.per_shard
            ],
            "trial_results": list(self.trials),
        }


def collect_harbor_results(
    root: Path, *, expected_tasks: tuple[str, ...] = ()
) -> HarborResultCollection:
    root = root.resolve()
    expected = tuple(dict.fromkeys(str(item) for item in expected_tasks if str(item)))
    result_paths = sorted(root.rglob("*result.json"))
    by_task: dict[str, tuple[dict[str, Any], str]] = {}
    conflicts: set[str] = set()
    ignored = 0
    duplicates = 0
    shard_counts: dict[str, set[str]] = {}
    failures: list[str] = []
    for path in result_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            failures.append(f"unreadable_result:{path.relative_to(root)}:{type(exc).__name__}")
            continue
        if not isinstance(payload, dict):
            failures.append(f"invalid_result_object:{path.relative_to(root)}")
            continue
        rows = _rows(payload)
        if not rows:
            ignored += 1
            continue
        shard = path.relative_to(root).parts[0] if path.relative_to(root).parts else "."
        for row in rows:
            task = _task_name(row)
            if not task:
                failures.append(f"trial_without_task:{path.relative_to(root)}")
                continue
            canonical = _canonical(row)
            existing = by_task.get(task)
            if existing is None:
                by_task[task] = (row, canonical)
                shard_counts.setdefault(shard, set()).add(task)
            elif existing[1] == canonical:
                duplicates += 1
            else:
                conflicts.add(task)
    for task in sorted(conflicts):
        by_task.pop(task, None)
        failures.append(f"conflicting_trial_result:{task}")
    observed = set(by_task)
    expected_set = set(expected)
    missing = tuple(sorted(expected_set - observed - conflicts))
    unexpected = tuple(sorted(observed - expected_set)) if expected else ()
    failures.extend(f"missing_expected_task:{task}" for task in missing)
    failures.extend(f"unexpected_task:{task}" for task in unexpected)
    trials = tuple(by_task[task][0] for task in sorted(by_task))
    solved = tuple(task for task in sorted(by_task) if _solved(by_task[task][0]))
    errored = tuple(
        task
        for task in sorted(by_task)
        if bool(by_task[task][0].get("exception_info"))
        and not bool(
            (by_task[task][0].get("verifier_result") or {}).get("rewards")
        )
    )
    return HarborResultCollection(
        trials=trials,
        expected_tasks=expected,
        missing_tasks=missing,
        unexpected_tasks=unexpected,
        solved_tasks=solved,
        errored_tasks=errored,
        failures=tuple(failures),
        result_files=len(result_paths),
        ignored_job_results=ignored,
        duplicate_identical_rows=duplicates,
        per_shard=tuple(
            (shard, len(tasks)) for shard, tasks in sorted(shard_counts.items())
        ),
    )


def _summary(collection: HarborResultCollection) -> str:
    expected = len(collection.expected_tasks)
    graded = sum(
        bool((row.get("verifier_result") or {}).get("rewards"))
        for row in collection.trials
    )
    lines = ["# TB2 miniswe baseline (sharded, no GT)", ""]
    if collection.failures:
        lines.extend(
            [
                f"> **INCOMPLETE**: {len(collection.failures)} integrity failure(s).",
                "",
                *(f"> - `{failure}`" for failure in collection.failures),
                "",
            ]
        )
    lines.extend(
        [
            f"- tasks planned: **{expected}**",
            f"- trials returned: **{len(collection.trials)}**",
            f"- graded: **{graded}**",
            f"- errored: **{len(collection.errored_tasks)}**",
            f"- solved: **{len(collection.solved_tasks)}/{expected or len(collection.trials)}**",
            f"- identical duplicate rows ignored: **{collection.duplicate_identical_rows}**",
            "",
            "| shard | unique trials |",
            "|---|---|",
            *(f"| {name} | {count} |" for name, count in collection.per_shard),
            "",
            "| task | solved | rewards / error |",
            "|---|---|---|",
        ]
    )
    for row in collection.trials:
        task = _task_name(row)
        rewards = (row.get("verifier_result") or {}).get("rewards")
        exception = (row.get("exception_info") or {}).get("exception_type")
        mark = "yes" if rewards and _solved(row) else "no" if rewards else "-"
        outcome = json.dumps(rewards) if rewards else (exception or "no reward")
        lines.append(
            f"| {task} | {mark} | {outcome} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--expected-json", default="[]")
    parser.add_argument("--merged", type=Path, default=Path("merged.json"))
    parser.add_argument("--summary", type=Path, default=Path("SUMMARY.md"))
    args = parser.parse_args(argv)
    expected_raw = json.loads(args.expected_json)
    if not isinstance(expected_raw, list):
        raise SystemExit("--expected-json must be a JSON list")
    collection = collect_harbor_results(
        args.root, expected_tasks=tuple(str(item) for item in expected_raw)
    )
    args.merged.write_text(
        json.dumps(collection.as_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    summary = _summary(collection)
    args.summary.write_text(summary, encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with Path(step_summary).open("a", encoding="utf-8") as handle:
            handle.write(summary)
    print(summary, end="")
    return 0 if not collection.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
