"""Fail-closed verification for the pre-outcome Terminal-Bench prediction.

This is a benchmark-integrity check, not an outcome evaluator.  It verifies
that the prediction was frozen before the candidate run, that it describes the
selected frozen profile exactly, and that the runtime proof commit is present
in the checked-out treatment commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _task_set_sha256(tasks: list[str]) -> str:
    canonical = "\n".join(sorted(str(task) for task in tasks)) + "\n"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _profile_tasks(baseline: dict[str, Any], profile_id: str) -> tuple[list[str], dict[str, Any]]:
    profiles = (baseline.get("manifest") or {}).get("profiles") or {}
    if profile_id not in profiles:
        raise ValueError(f"unknown frozen comparison profile: {profile_id}")
    profile = profiles[profile_id]
    if profile.get("task_source") == "all_rows":
        tasks = sorted(str(row["task"]) for row in baseline.get("rows") or [])
    else:
        tasks = sorted(str(task) for task in profile.get("task_ids") or [])
    return tasks, profile


def _is_ancestor(commit: str, current: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, current],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def verify(
    *,
    prediction_path: Path,
    baseline_path: Path,
    profile_id: str,
    current_commit: str,
) -> dict[str, Any]:
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if prediction.get("prediction_before_outcome") is not True:
        raise ValueError("prediction is not marked as frozen before outcome")
    if prediction.get("outcome_run_executed") is not False:
        raise ValueError("prediction already claims an outcome run was executed")

    tasks, profile = _profile_tasks(baseline, profile_id)
    expected_digest = _task_set_sha256(tasks)
    if len(tasks) != int(profile.get("task_count", -1)):
        raise ValueError("frozen profile task count does not match its task list")
    if expected_digest != str(profile.get("task_set_sha256") or ""):
        raise ValueError("frozen profile task-set hash is invalid")
    if prediction.get("task_profile") != profile_id:
        raise ValueError("prediction profile does not match selected profile")
    if prediction.get("task_count") != len(tasks):
        raise ValueError("prediction task count does not match selected profile")
    if prediction.get("task_order") != tasks:
        raise ValueError("prediction task order does not match selected profile")

    rows = prediction.get("predictions")
    if not isinstance(rows, list) or len(rows) != len(tasks):
        raise ValueError("prediction rows do not cover the selected profile")
    row_tasks = [row.get("task") for row in rows if isinstance(row, dict)]
    if row_tasks != tasks:
        raise ValueError("prediction rows are not in the frozen task order")
    if any(not isinstance(row.get("predicted_solved"), bool) for row in rows):
        raise ValueError("every prediction row needs a boolean predicted_solved")

    aggregate = prediction.get("aggregate_prediction") or {}
    predicted_solved = sum(bool(row["predicted_solved"]) for row in rows)
    if aggregate.get("point_solved") != predicted_solved:
        raise ValueError("aggregate point_solved disagrees with prediction rows")
    if aggregate.get("point_resolve_rate") != predicted_solved / len(tasks):
        raise ValueError("aggregate point_resolve_rate disagrees with prediction rows")

    baseline_digest = _sha256(baseline_path)
    source_baseline = (prediction.get("source_artifacts") or {}).get("frozen_gt_off") or {}
    if source_baseline.get("sha256") != baseline_digest:
        raise ValueError("prediction does not bind the checked-in frozen baseline hash")

    proof_commit = str(prediction.get("candidate_runtime_proof_commit") or "")
    runtime_commit = str(prediction.get("candidate_runtime_commit") or "")
    commits = (
        ("candidate runtime proof", proof_commit),
        ("candidate runtime", runtime_commit),
    )
    for label, commit in commits:
        if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit.lower()):
            raise ValueError(f"{label} is not a full commit SHA")
        if not _is_ancestor(commit, current_commit):
            raise ValueError(f"{label} commit is not an ancestor of the treatment commit")

    return {
        "schema": "gt.frozen_outcome_prediction_proof.v1",
        "prediction_path": prediction_path.as_posix(),
        "prediction_sha256": _sha256(prediction_path),
        "profile_id": profile_id,
        "task_count": len(tasks),
        "task_set_sha256": expected_digest,
        "prediction_before_outcome": True,
        "outcome_run_executed": False,
        "candidate_runtime_commit": runtime_commit,
        "candidate_runtime_proof_commit": proof_commit,
        "predicted_solved": predicted_solved,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--current-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    proof = verify(
        prediction_path=args.prediction,
        baseline_path=args.baseline,
        profile_id=args.profile,
        current_commit=args.current_commit,
    )
    args.output.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
