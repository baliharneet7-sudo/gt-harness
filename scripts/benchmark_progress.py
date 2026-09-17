"""Create and aggregate live benchmark progress from official verifier evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA = "gt.benchmark_progress.v1"
STATES = ("passed", "verifier_failed", "infrastructure_failed")


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def official_harbor_reward(result_path: Path, trial: dict[str, Any]) -> tuple[int | None, str]:
    """Return Harbor's canonical official reward, including its artifact fallback.

    Harbor may leave ``verifier_result`` null when the installed agent exits
    nonzero after submitting, even though the official verifier subsequently
    completes and writes ``verifier/reward.txt`` and ``verifier/ctrf.json``.
    Completed verifier timestamps plus both canonical artifacts are sufficient
    official evidence; no model or verifier rerun is involved.
    """
    verifier = trial.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    reward = rewards.get("reward") if isinstance(rewards, dict) else None
    if type(reward) in (int, float) and reward in (0, 1):
        return int(reward), "harbor_verifier_result"

    timing = trial.get("verifier")
    if (
        not isinstance(timing, dict)
        or not timing.get("started_at")
        or not timing.get("finished_at")
    ):
        return None, ""
    reward_path = result_path.parent / "verifier" / "reward.txt"
    ctrf_path = result_path.parent / "verifier" / "ctrf.json"
    if not reward_path.is_file() or not ctrf_path.is_file():
        return None, ""
    try:
        artifact_reward = float(reward_path.read_text(encoding="utf-8").strip())
        ctrf = _read_object(ctrf_path)
        summary = (ctrf.get("results") or {}).get("summary") or {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None, ""
    if artifact_reward not in (0.0, 1.0) or not isinstance(summary, dict) or not summary:
        return None, ""
    return int(artifact_reward), "official_verifier_artifact"


def expected_task_ids(value: str) -> list[str]:
    if not value.strip():
        return []
    payload = json.loads(value)
    rows = payload if isinstance(payload, list) else payload.get("include", [])
    if not isinstance(rows, list):
        raise ValueError("expected task JSON must be a list or matrix include object")
    tasks: list[str] = []
    for row in rows:
        if isinstance(row, str):
            tasks.append(row)
        elif isinstance(row, dict) and isinstance(row.get("task"), str):
            tasks.append(row["task"])
        elif isinstance(row, dict) and isinstance(row.get("tasks"), str):
            tasks.extend(item.strip() for item in row["tasks"].split(",") if item.strip())
        else:
            raise ValueError("expected task JSON contains an unsupported row")
    if not tasks or any(not task for task in tasks) or len(tasks) != len(set(tasks)):
        raise ValueError("expected tasks must be nonempty and unique")
    return tasks


def outcome_from_official(receipt: dict[str, Any], task_id: str) -> dict[str, Any]:
    if receipt.get("schema") != "gt.official_verifier_result.v1":
        raise ValueError("unsupported official verifier receipt schema")
    if receipt.get("task_id") != task_id:
        raise ValueError("official verifier receipt task identity mismatch")
    reward = receipt.get("reward")
    graded = receipt.get("status") == "GRADED" and type(reward) in (int, float) and reward in (0, 1)
    if graded:
        return {
            "task_id": task_id,
            "state": "passed" if reward == 1 else "verifier_failed",
            "official_verifier": True,
            "reward": int(reward),
            "failure_class": "graded",
            "error_code": "",
        }
    return {
        "task_id": task_id,
        "state": "infrastructure_failed",
        "official_verifier": False,
        "reward": None,
        "failure_class": str(receipt.get("failure_class") or "malformed_result"),
        "error_code": str(receipt.get("error_code") or "official_verifier_result_malformed"),
    }


def emit_official(root: Path, suite: str, task_id: str) -> dict[str, Any]:
    matches = sorted(root.rglob("official-verifier-result.json")) if root.exists() else []
    if len(matches) == 1:
        task = outcome_from_official(_read_object(matches[0]), task_id)
    else:
        task = {
            "task_id": task_id,
            "state": "infrastructure_failed",
            "official_verifier": False,
            "reward": None,
            "failure_class": "missing_result" if not matches else "ambiguous_result",
            "error_code": "official_verifier_result_missing"
            if not matches
            else "multiple_official_verifier_results",
        }
    return {"schema": SCHEMA, "benchmark_suite": suite, "tasks": [task]}


def emit_harbor(
    root: Path,
    task_id: str,
    *,
    model: str = "",
    effective_model: str = "",
    treatment_sha: str = "",
    gt_source_sha: str = "",
) -> dict[str, Any]:
    """Read Terminal-Bench's official Harbor verifier result without job-status inference."""
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(root.rglob("result.json")) if root.exists() else []:
        payload = _read_object(path)
        runner_task = str(payload.get("task_name") or "").rsplit("/", 1)[-1]
        if runner_task == task_id and payload.get("trial_name"):
            matches.append((path, payload))
    if len(matches) == 1:
        result_path, trial = matches[0]
        reward, reward_source = official_harbor_reward(result_path, trial)
        if reward is not None:
            task = {
                "task_id": task_id,
                "state": "passed" if reward == 1 else "verifier_failed",
                "official_verifier": True,
                "reward": int(reward),
                "failure_class": "graded",
                "error_code": "",
                "reward_source": reward_source,
            }
        else:
            exception = trial.get("exception_info")
            task = {
                "task_id": task_id,
                "state": "infrastructure_failed",
                "official_verifier": False,
                "reward": None,
                "failure_class": "runner_error" if exception else "missing_verifier",
                "error_code": "harbor_trial_failed"
                if exception
                else "official_verifier_reward_missing",
            }
    else:
        task = {
            "task_id": task_id,
            "state": "infrastructure_failed",
            "official_verifier": False,
            "reward": None,
            "failure_class": "missing_result" if not matches else "ambiguous_result",
            "error_code": "harbor_trial_result_missing"
            if not matches
            else "multiple_harbor_trial_results",
        }
    receipt = {"schema": SCHEMA, "benchmark_suite": "terminal-bench-2", "tasks": [task]}
    metadata = {
        "model": model,
        "effective_model": effective_model,
        "treatment_sha": treatment_sha,
        "gt_source_sha": gt_source_sha,
    }
    receipt.update({key: value for key, value in metadata.items() if value})
    return receipt


def emit_live(planned_csv: str, results_path: Path) -> dict[str, Any]:
    planned = [item.strip() for item in planned_csv.split(",") if item.strip()]
    if not planned or len(planned) != len(set(planned)):
        raise ValueError("planned Live Lite tasks must be nonempty and unique")
    official = _read_object(results_path) if results_path.is_file() else {}
    unexpected = sorted(set(official) - set(planned))
    if unexpected:
        raise ValueError(f"unexpected official result: {unexpected[0]}")
    tasks = []
    for task_id in planned:
        result = official.get(task_id)
        reward = result.get("reward") if isinstance(result, dict) else None
        if type(reward) in (int, float) and reward in (0, 1):
            tasks.append(
                {
                    "task_id": task_id,
                    "state": "passed" if reward == 1 else "verifier_failed",
                    "official_verifier": True,
                    "reward": int(reward),
                    "failure_class": "graded",
                    "error_code": "",
                }
            )
        else:
            tasks.append(
                {
                    "task_id": task_id,
                    "state": "infrastructure_failed",
                    "official_verifier": False,
                    "reward": None,
                    "failure_class": str((result or {}).get("failure_class") or "missing_result"),
                    "error_code": str(
                        (result or {}).get("error_code") or "official_verifier_result_missing"
                    ),
                }
            )
    return {"schema": SCHEMA, "benchmark_suite": "swe-bench-live-lite", "tasks": tasks}


def _progress_files(root: Path) -> Iterable[Path]:
    yield from sorted(root.rglob("benchmark-progress.json")) if root.exists() else ()


def aggregate(root: Path, expected: list[str], *, finalize_missing: bool = False) -> dict[str, Any]:
    outcomes: dict[str, dict[str, Any]] = {}
    suites: set[str] = set()
    for path in _progress_files(root):
        receipt = _read_object(path)
        if receipt.get("schema") != SCHEMA or not isinstance(receipt.get("tasks"), list):
            raise ValueError(f"invalid progress receipt: {path}")
        suites.add(str(receipt.get("benchmark_suite") or ""))
        for task in receipt["tasks"]:
            if not isinstance(task, dict) or task.get("state") not in STATES:
                raise ValueError(f"invalid task outcome: {path}")
            task_id = task.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                raise ValueError(f"invalid task identity: {path}")
            previous = outcomes.get(task_id)
            if previous is not None and previous != task:
                raise ValueError(f"conflicting duplicate outcome: {task_id}")
            outcomes[task_id] = task
    unexpected = sorted(set(outcomes) - set(expected))
    if unexpected:
        raise ValueError(f"unexpected progress task: {unexpected[0]}")
    if finalize_missing:
        for task_id in expected:
            outcomes.setdefault(
                task_id,
                {
                    "task_id": task_id,
                    "state": "infrastructure_failed",
                    "official_verifier": False,
                    "reward": None,
                    "failure_class": "missing_result",
                    "error_code": "progress_artifact_missing",
                },
            )
    counts = {state: sum(row["state"] == state for row in outcomes.values()) for state in STATES}
    completed = len(outcomes)
    return {
        "schema": SCHEMA,
        "benchmark_suite": next(iter(suites)) if len(suites) == 1 else "",
        "total": len(expected),
        "completed": completed,
        "officially_graded": counts["passed"] + counts["verifier_failed"],
        "passed": counts["passed"],
        "verifier_failed": counts["verifier_failed"],
        "infrastructure_failed": counts["infrastructure_failed"],
        "remaining": len(expected) - completed,
        "tasks": [outcomes[task] for task in expected if task in outcomes],
    }


def _write(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    official = sub.add_parser("emit-official")
    official.add_argument("--root", type=Path, required=True)
    official.add_argument("--suite", required=True)
    official.add_argument("--task-id", required=True)
    official.add_argument("--output", type=Path, required=True)
    harbor = sub.add_parser("emit-harbor")
    harbor.add_argument("--root", type=Path, required=True)
    harbor.add_argument("--task-id", required=True)
    harbor.add_argument("--output", type=Path, required=True)
    harbor.add_argument("--model", default="")
    harbor.add_argument("--effective-model", default="")
    harbor.add_argument("--treatment-sha", default="")
    harbor.add_argument("--gt-source-sha", default="")
    live = sub.add_parser("emit-live")
    live.add_argument("--planned-csv", required=True)
    live.add_argument("--results", type=Path, required=True)
    live.add_argument("--output", type=Path, required=True)
    combined = sub.add_parser("aggregate")
    combined.add_argument("--root", type=Path, required=True)
    combined.add_argument("--expected-tasks-json", required=True)
    combined.add_argument("--finalize-missing", action="store_true")
    combined.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "emit-official":
        payload = emit_official(args.root, args.suite, args.task_id)
    elif args.command == "emit-harbor":
        payload = emit_harbor(
            args.root,
            args.task_id,
            model=args.model,
            effective_model=args.effective_model,
            treatment_sha=args.treatment_sha,
            gt_source_sha=args.gt_source_sha,
        )
    elif args.command == "emit-live":
        payload = emit_live(args.planned_csv, args.results)
    else:
        payload = aggregate(
            args.root,
            expected_task_ids(args.expected_tasks_json),
            finalize_missing=args.finalize_missing,
        )
    _write(payload, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
