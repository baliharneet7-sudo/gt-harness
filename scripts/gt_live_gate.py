"""Acceptance gate for a live GT-on Mini-SWE campaign.

The input is the machine JSON emitted by ``scripts/gt_audit.py``. This gate
does not inspect transcript markers. Attribution comes from the hash-chained
trigger/producer/delivery/provider/response records already verified by the
auditor.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from gt_engine.attribution import DIRECT_FEATURES


def _model_values(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"model", "model_name"} and isinstance(item, str):
                found.add(item)
            found.update(_model_values(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_model_values(item))
    return found


def evaluate_live_gate(
    audit: dict[str, Any],
    *,
    min_witnessed: int,
    min_action_consistent: int = 0,
    expected_tasks: int,
    expected_model: str,
    expected_temperature: float | None = None,
    require_complete_census: bool = False,
    required_lifecycle: tuple[str, ...] = (),
    run_dir: Path | None = None,
) -> dict[str, Any]:
    tasks = list(audit.get("tasks") or ())
    issues: list[str] = []
    witnessed: set[str] = set()
    dark: list[str] = []
    faults: list[str] = []
    unexposed: list[str] = []
    actions_consistent: set[str] = set()
    lifecycle_observed: set[str] = set()
    provider_temperatures: set[float] = set()
    complete_census = True
    expected_feature_ids = set(DIRECT_FEATURES)
    valid_statuses = {
        "INELIGIBLE",
        "TRIGGERED_DARK",
        "SUPPRESSED_WITH_REASON",
        "DELIVERED_UNEXPOSED",
        "EXPOSED",
        "WITNESSED",
        "TELEMETRY_FAULT",
    }

    if len(tasks) != expected_tasks:
        issues.append(
            f"task count {len(tasks)} != expected {expected_tasks}"
        )
    for task in tasks:
        task_name = str(task.get("task_name") or "?")
        if task.get("agent_error") or task.get("exception_info"):
            issues.append(f"{task_name}: unhealthy agent/harness result")
        for issue in task.get("attribution_issues") or ():
            issues.append(f"{task_name}: attribution: {issue}")
        for issue in task.get("ledger_issues") or ():
            issues.append(f"{task_name}: ledger: {issue}")
        for issue in task.get("dose_violations") or ():
            issues.append(f"{task_name}: dose: {issue}")
        lifecycle_observed.update(
            str(phase)
            for phase in (task.get("lifecycle_checkpoints") or {})
        )
        task_features = task.get("feature_attribution") or {}
        if require_complete_census:
            actual_ids = set(task_features)
            missing = sorted(expected_feature_ids - actual_ids)
            extra = sorted(actual_ids - expected_feature_ids)
            invalid = sorted(
                feature_id
                for feature_id, item in task_features.items()
                if str(item.get("status") or "") not in valid_statuses
            )
            if missing or extra or invalid:
                complete_census = False
                issues.append(
                    f"{task_name}: incomplete feature census "
                    f"(missing={missing}, extra={extra}, invalid={invalid})"
                )
        for value in task.get("provider_temperatures") or ():
            if isinstance(value, int | float):
                provider_temperatures.add(float(value))
        for feature_id, item in task_features.items():
            status = str(item.get("status") or "")
            if status == "WITNESSED":
                witnessed.add(feature_id)
            elif status == "TRIGGERED_DARK":
                dark.append(f"{task_name}:{feature_id}")
            elif status == "TELEMETRY_FAULT":
                faults.append(f"{task_name}:{feature_id}")
            if item.get("deliveries") and not item.get("exposed"):
                unexposed.append(f"{task_name}:{feature_id}")
            if item.get("action_consistent"):
                actions_consistent.add(feature_id)

    if dark:
        issues.append("eligible trigger(s) went dark: " + ", ".join(dark))
    if faults:
        issues.append("telemetry fault(s): " + ", ".join(faults))
    if unexposed:
        issues.append("unexposed delivery/owner(s): " + ", ".join(unexposed))
    if len(witnessed) < min_witnessed:
        issues.append(
            f"witnessed identities {len(witnessed)} < required "
            f"{min_witnessed}"
        )
    if len(actions_consistent) < min_action_consistent:
        issues.append(
            f"action-consistent identities {len(actions_consistent)} < required "
            f"{min_action_consistent}"
        )
    if expected_temperature is not None and provider_temperatures != {
        float(expected_temperature)
    }:
        issues.append(
            f"provider temperature must be exactly {float(expected_temperature)}; "
            f"observed={sorted(provider_temperatures)}"
        )
    missing_lifecycle = sorted(set(required_lifecycle) - lifecycle_observed)
    if missing_lifecycle:
        issues.append(
            "missing SDLC lifecycle checkpoint(s): "
            + ", ".join(missing_lifecycle)
        )

    observed_models: set[str] = set()
    if run_dir is not None and run_dir.is_dir():
        for result_path in run_dir.glob("*/result.json"):
            try:
                observed_models.update(_model_values(json.loads(
                    result_path.read_text(encoding="utf-8")
                )))
            except (OSError, json.JSONDecodeError):
                issues.append(f"{result_path.parent.name}: unreadable result.json")
    if expected_model and expected_model not in observed_models:
        issues.append(
            f"expected model {expected_model!r} not found in result metadata; "
            f"observed={sorted(observed_models)}"
        )

    return {
        "schema": "gt.live_acceptance.v1",
        "passed": not issues,
        "task_count": len(tasks),
        "expected_tasks": expected_tasks,
        "min_witnessed": min_witnessed,
        "min_action_consistent": min_action_consistent,
        "witnessed_count": len(witnessed),
        "witnessed_features": sorted(witnessed),
        "action_consistent_features": sorted(actions_consistent),
        "required_lifecycle": sorted(set(required_lifecycle)),
        "lifecycle_observed": sorted(lifecycle_observed),
        "missing_lifecycle": missing_lifecycle,
        "dark": dark,
        "faults": faults,
        "unexposed": unexposed,
        "observed_models": sorted(observed_models),
        "expected_temperature": expected_temperature,
        "provider_temperatures": sorted(provider_temperatures),
        "complete_census": complete_census,
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit_json")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--min-witnessed", type=int, default=9)
    parser.add_argument("--min-action-consistent", type=int, default=0)
    parser.add_argument("--expected-tasks", type=int, default=5)
    parser.add_argument("--expected-model", default="deepseek-v4-flash")
    parser.add_argument("--expected-temperature", type=float)
    parser.add_argument("--require-complete-census", action="store_true")
    parser.add_argument(
        "--require-lifecycle",
        default="",
        help="comma-separated SDLC checkpoint phases required across the run",
    )
    parser.add_argument("--json", dest="output_json")
    args = parser.parse_args(argv)

    audit_path = Path(args.audit_json)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    report = evaluate_live_gate(
        audit,
        min_witnessed=args.min_witnessed,
        min_action_consistent=args.min_action_consistent,
        expected_tasks=args.expected_tasks,
        expected_model=args.expected_model,
        expected_temperature=args.expected_temperature,
        require_complete_census=args.require_complete_census,
        required_lifecycle=tuple(
            phase.strip()
            for phase in args.require_lifecycle.split(",")
            if phase.strip()
        ),
        run_dir=Path(args.run_dir),
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output_json:
        Path(args.output_json).write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
