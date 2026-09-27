"""Record the GT delivery a task actually received in its progress receipt.

The runner writes ``agent/miniswe_report.json`` with the delivery mode it ran,
whether the treatment was valid (an attached run whose graph never became
ready is not a GT result), and the step limit it enforced. The official
verifier knows none of that, so a progress receipt alone cannot tell a GT run
from a degraded one. This copies those fields onto the task row as
``gt_delivery`` so aggregation can count invalid treatments instead of scoring
them as GT.

A missing report is recorded, not guessed: ``report_present: false``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.gh_annotations import emit_line, gh_command


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def find_report(results: Path) -> Path | None:
    reports = sorted(results.rglob("agent/miniswe_report.json"))
    return reports[0] if len(reports) == 1 else None


def delivery_fields(report: dict[str, Any] | None, *, requested_mode: str,
                    requested_step_limit: int) -> dict[str, Any]:
    if report is None:
        return {
            "report_present": False,
            "requested_mode": requested_mode,
            "requested_step_limit": requested_step_limit,
            "treatment_valid": False,
            "treatment_invalid_reason": "miniswe_report_missing",
        }
    delivery = report.get("gt_delivery") or {}
    mode = delivery.get("gt_delivery_mode")
    effective = report.get("effective_step_limit")
    reason = str(delivery.get("treatment_invalid_reason") or "")
    valid = delivery.get("treatment_valid", True) is not False
    if mode != requested_mode:
        valid, reason = False, reason or f"delivery_mode_mismatch:{mode}"
    return {
        "report_present": True,
        "requested_mode": requested_mode,
        "gt_delivery_mode": mode,
        "treatment_valid": valid,
        "treatment_invalid_reason": reason,
        "requested_step_limit": requested_step_limit,
        "effective_step_limit": effective,
        "step_limit_matches": effective == requested_step_limit,
        **{key: delivery.get(key) for key in (
            "gt_tool_calls", "augment_calls", "augment_hits", "gt_bytes_delivered",
            "gt_context_referenced", "features_reached", "feature_inventory",
            "edit_augment_hits", "failure_augment_hits", "gt_plan_delivered",
        ) if key in delivery},
    }


def annotate(progress: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    tasks = progress.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 1 or not isinstance(tasks[0], dict):
        raise ValueError("progress receipt must hold exactly one task row")
    return {**progress, "tasks": [{**tasks[0], "gt_delivery": fields}]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--progress", type=Path, required=True)
    parser.add_argument("--requested-mode", required=True, choices=["attached", "push"])
    parser.add_argument("--requested-step-limit", type=int, required=True)
    args = parser.parse_args(argv)
    progress = _read(args.progress)
    if progress is None:
        emit_line(gh_command("error", "GT delivery", f"unreadable progress receipt {args.progress}"))
        return 1
    report_path = find_report(args.results)
    fields = delivery_fields(
        _read(report_path) if report_path else None,
        requested_mode=args.requested_mode,
        requested_step_limit=args.requested_step_limit,
    )
    args.progress.write_text(
        json.dumps(annotate(progress, fields), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not fields["treatment_valid"]:
        emit_line(gh_command("warning", "GT treatment invalid", str(fields["treatment_invalid_reason"])))
    if fields.get("step_limit_matches") is False:
        emit_line(gh_command(
            "warning", "Step limit mismatch",
            f"requested {args.requested_step_limit}, enforced {fields.get('effective_step_limit')}",
        ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
