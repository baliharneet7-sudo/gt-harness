#!/usr/bin/env python3
"""Fail-closed outcome and efficiency gate for a frozen DeepSWE A/B pair."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

IDENTITY_FIELDS = (
    "benchmark_sha",
    "model",
    "provider",
    "temperature",
    "step_limit",
    "execution_budget_sec",
    "runner",
)
RESOURCE_FIELDS = (
    "total_tokens",
    "provider_calls",
    "decision_actions",
    "provider_cost_usd",
)


@dataclass(frozen=True, slots=True)
class DeepSweReleaseReport:
    phase: str
    passed: bool
    failures: tuple[str, ...]
    baseline_solved: int
    treatment_solved: int
    losses: tuple[str, ...]
    flips: tuple[str, ...]
    common_solved: tuple[str, ...]
    common_solved_deltas: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rows(arm: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in arm.get("rows") or ():
        if not isinstance(row, dict):
            continue
        task = str(row.get("task") or "").strip()
        if task and task not in rows:
            rows[task] = row
    return rows


def _uncensored_solved(row: dict[str, Any]) -> bool:
    return bool(row.get("solved") is True and not row.get("exception"))


def _number(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def assess_deepswe_release(
    baseline: dict[str, Any],
    treatment: dict[str, Any],
    *,
    phase: str,
) -> DeepSweReleaseReport:
    """Assess a matched pair without inferring missing evidence as success."""

    if phase not in {"preservation", "promotion"}:
        raise ValueError("phase must be preservation or promotion")
    failures: list[str] = []
    if baseline.get("schema") != treatment.get("schema"):
        failures.append("schema_mismatch")
    baseline_manifest = baseline.get("manifest") or {}
    treatment_manifest = treatment.get("manifest") or {}
    for field in IDENTITY_FIELDS:
        if field not in baseline_manifest or field not in treatment_manifest:
            failures.append(f"manifest_missing:{field}")
        elif baseline_manifest[field] != treatment_manifest[field]:
            failures.append(f"manifest_mismatch:{field}")
    gt_commit = str(treatment_manifest.get("gt_commit") or "")
    if len(gt_commit) != 40:
        failures.append("treatment_gt_commit_not_exact")

    baseline_rows = _rows(baseline)
    treatment_rows = _rows(treatment)
    if set(baseline_rows) != set(treatment_rows):
        failures.append("task_set_mismatch")
    for task, row in (*baseline_rows.items(), *treatment_rows.items()):
        for metric in RESOURCE_FIELDS:
            if _number(row, metric) is None:
                failures.append(f"missing_metric:{task}:{metric}")
    for task, row in treatment_rows.items():
        if row.get("exception"):
            failures.append(f"censored_treatment:{task}")

    baseline_solved_tasks = {
        task for task, row in baseline_rows.items() if _uncensored_solved(row)
    }
    treatment_solved_tasks = {
        task for task, row in treatment_rows.items() if _uncensored_solved(row)
    }
    losses = tuple(sorted(baseline_solved_tasks - treatment_solved_tasks))
    flips = tuple(sorted(treatment_solved_tasks - baseline_solved_tasks))
    common = tuple(sorted(baseline_solved_tasks & treatment_solved_tasks))
    failures.extend(f"baseline_solve_regression:{task}" for task in losses)

    deltas: dict[str, float] = {}
    for metric in RESOURCE_FIELDS:
        baseline_values = [_number(baseline_rows[task], metric) for task in common]
        treatment_values = [_number(treatment_rows[task], metric) for task in common]
        if any(value is None for value in (*baseline_values, *treatment_values)):
            deltas[metric] = 0.0
            continue
        delta = sum(value or 0.0 for value in treatment_values) - sum(
            value or 0.0 for value in baseline_values
        )
        deltas[metric] = round(delta, 9)
        if delta > 0:
            failures.append(f"common_solved_resource_regression:{metric}")

    if phase == "promotion":
        if not flips:
            failures.append("no_positive_flip")
        if len(treatment_solved_tasks) <= len(baseline_solved_tasks):
            failures.append("no_net_solve_improvement")

    return DeepSweReleaseReport(
        phase=phase,
        passed=not failures,
        failures=tuple(dict.fromkeys(failures)),
        baseline_solved=len(baseline_solved_tasks),
        treatment_solved=len(treatment_solved_tasks),
        losses=losses,
        flips=flips,
        common_solved=common,
        common_solved_deltas=deltas,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--treatment", type=Path, required=True)
    parser.add_argument(
        "--phase", choices=("preservation", "promotion"), required=True
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    treatment = json.loads(args.treatment.read_text(encoding="utf-8"))
    report = assess_deepswe_release(baseline, treatment, phase=args.phase)
    payload = json.dumps(report.as_dict(), indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
