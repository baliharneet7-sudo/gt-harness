"""Build a caller-owned smoke manifest from recorded baseline outcomes.

The script selects measured previous regressions first, preserves measured
positive flips, then adds a caller-selected number of stable controls. It does
not run an agent, fetch a baseline, or encode task IDs in product code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows(payload: dict[str, Any], *, label: str) -> dict[str, bool]:
    direct = payload.get("rows")
    if isinstance(direct, list):
        result = {}
        for row in direct:
            if isinstance(row, dict) and isinstance(row.get("task"), str):
                result[row["task"]] = bool(row.get("solved"))
        if result:
            return result

    trials = payload.get("trial_results")
    if not isinstance(trials, list):
        raise ValueError(f"{label} has neither rows nor trial_results")
    result = {}
    for trial in trials:
        if not isinstance(trial, dict) or not isinstance(trial.get("task_name"), str):
            continue
        rewards = (trial.get("verifier_result") or {}).get("rewards") or {}
        numeric = [value for value in rewards.values() if isinstance(value, (int, float))]
        result[trial["task_name"]] = bool(numeric) and all(value >= 1 for value in numeric)
    if not result:
        raise ValueError(f"{label} contains no task outcomes")
    return result


def build_manifest(
    *,
    baseline_path: Path,
    previous_path: Path,
    stable_control_count: int,
) -> dict[str, Any]:
    if stable_control_count < 0:
        raise ValueError("stable_control_count must be non-negative")
    baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    previous_payload = json.loads(previous_path.read_text(encoding="utf-8"))
    baseline = _rows(baseline_payload, label="baseline")
    previous = _rows(previous_payload, label="previous GT")
    common = sorted(set(baseline) & set(previous))
    regressions = [task for task in common if baseline[task] and not previous[task]]
    positive_flips = [task for task in common if not baseline[task] and previous[task]]
    stable_controls = [
        task for task in common if baseline[task] and previous[task]
    ][:stable_control_count]
    selected = regressions + positive_flips + stable_controls
    return {
        "schema": "gt.caller_owned_regression_smoke_manifest.v1",
        "selection_rule": {
            "regressions": "baseline_solved_and_previous_gt_unsolved",
            "positive_flips": "baseline_unsolved_and_previous_gt_solved",
            "stable_controls": "lexicographically_first_common_baseline_and_previous_solved_rows",
            "stable_control_count": stable_control_count,
        },
        "source_artifacts": {
            "baseline": baseline_path.resolve().as_posix(),
            "baseline_sha256": _sha256(baseline_path),
            "previous_gt": previous_path.resolve().as_posix(),
            "previous_gt_sha256": _sha256(previous_path),
        },
        "task_count": len(selected),
        "tasks": selected,
        "regressions": regressions,
        "positive_flips": positive_flips,
        "stable_controls": stable_controls,
        "outcome_run_executed": False,
    }


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--previous-gt", type=Path, required=True)
    parser.add_argument("--stable-control-count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = {args.baseline.resolve(), args.previous_gt.resolve()}
    if args.output.resolve() in inputs:
        raise SystemExit("output must not overwrite an input artifact")
    payload = build_manifest(
        baseline_path=args.baseline,
        previous_path=args.previous_gt,
        stable_control_count=args.stable_control_count,
    )
    _write_atomic(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
