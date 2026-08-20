#!/usr/bin/env python3
"""Post-hoc TB2 outcome/trajectory forensics without grader-only inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from gt_engine.delivery_audit import audit_provider_deliveries
from gt_engine.runtime_gate import audit_runtime_receipt
from scripts.tb2_promotion_gate import RESOURCE_FIELDS, task_set_sha256


def _rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("task") or ""): row
        for row in payload.get("rows") or ()
        if isinstance(row, dict) and row.get("task")
    }


def _find_task_file(root: Path | None, task: str, name: str) -> Path | None:
    if root is None or not root.is_dir():
        return None
    candidates = [
        path for path in root.rglob(name) if task in path.parts or task in str(path)
    ]
    return (
        sorted(candidates, key=lambda path: (len(path.parts), str(path)))[-1]
        if candidates
        else None
    )


def _action_hashes(path: Path | None) -> tuple[str, ...]:
    if path is None:
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    hashes: list[str] = []
    for message in payload.get("messages") or ():
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for action in (message.get("extra") or {}).get("actions") or ():
            if not isinstance(action, dict):
                continue
            command = str(action.get("command") or "")
            if command:
                hashes.append(hashlib.sha256(command.encode("utf-8")).hexdigest())
    return tuple(hashes)


def _trajectory_steps(path: Path | None) -> tuple[dict[str, Any], ...]:
    if path is None:
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    steps: list[dict[str, Any]] = []
    call = 0
    action_ordinal = 0
    for message in payload.get("messages") or ():
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        call += 1
        actions = []
        for action in (message.get("extra") or {}).get("actions") or ():
            if not isinstance(action, dict):
                continue
            command = str(action.get("command") or "")
            if command:
                action_ordinal += 1
                actions.append(
                    {
                        "ordinal": action_ordinal,
                        "command": command,
                        "sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
                    }
                )
        reasoning = str(
            message.get("reasoning_content")
            or ((message.get("extra") or {}).get("reasoning_content"))
            or ""
        )
        steps.append({"call": call, "reasoning_content": reasoning, "actions": actions})
    return tuple(steps)


def _step_for_action(
    steps: tuple[dict[str, Any], ...], action_ordinal: int | None
) -> dict[str, Any] | None:
    if action_ordinal is None:
        return None
    return next(
        (
            step
            for step in steps
            if any(action.get("ordinal") == action_ordinal for action in step["actions"])
        ),
        None,
    )


def _command_at(
    steps: tuple[dict[str, Any], ...], action_ordinal: int | None
) -> str:
    if action_ordinal is None:
        return ""
    for step in steps:
        for action in step["actions"]:
            if action.get("ordinal") == action_ordinal:
                return str(action.get("command") or "")
    return ""


def _delivery_influence(
    receipt: dict[str, Any], *, through_call: int | None, reasoning: str
) -> list[dict[str, Any]]:
    rows, _failures, _totals = audit_provider_deliveries(receipt, task="forensics")
    result: list[dict[str, Any]] = []
    reasoning_lower = reasoning.lower()
    for row in rows:
        delivered = row.get("delivered_before_call")
        if through_call is not None and isinstance(delivered, int) and delivered > through_call:
            continue
        anchors: list[str] = []
        for certificate in row.get("value_certificates") or ():
            anchors.extend(str(item) for item in certificate.get("anchors") or () if str(item))
        for fact in row.get("raw", {}).get("facts") or ():
            if isinstance(fact, dict) and str(fact.get("path") or ""):
                anchors.append(str(fact["path"]))
        anchors = list(dict.fromkeys(anchors))
        mentioned = [anchor for anchor in anchors if anchor.lower() in reasoning_lower]
        result.append(
            {
                "surface": row["surface"],
                "delivered_before_call": delivered,
                "claim_ids": list(row["claim_ids"]),
                "value_certificates": list(row.get("value_certificates") or ()),
                "anchors": anchors,
                "reasoning_anchor_mentions": mentioned,
                "reasoning_uptake": bool(mentioned),
                "exploration_replacement": dict(
                    row.get("raw", {}).get("exploration_replacement_receipt") or {}
                ),
            }
        )
    return result


def _exit_status(path: Path | None) -> str:
    if path is None:
        return ""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return str((payload.get("info") or {}).get("exit_status") or "")


def _first_divergence(before: tuple[str, ...], after: tuple[str, ...]) -> int | None:
    for index, (left, right) in enumerate(zip(before, after, strict=False), start=1):
        if left != right:
            return index
    if len(before) != len(after):
        return min(len(before), len(after)) + 1
    return None


def _first_gt_changed_call(receipt: dict[str, Any]) -> int | None:
    changed: list[int] = []
    for row in receipt.get("model_call_contexts") or ():
        if not isinstance(row, dict):
            continue
        control = str(
            row.get("control_provider_messages_sha256")
            or row.get("stock_provider_messages_sha256")
            or ""
        )
        final = str(row.get("provider_messages_sha256") or "")
        call = int(row.get("call") or 0)
        if call and control and final and control != final:
            changed.append(call)
    return min(changed) if changed else None


def _receipt_summary(path: Path | None, task: str) -> dict[str, Any]:
    if path is None:
        return {
            "available": False,
            "first_gt_changed_call": None,
            "release_integrity_failures": [f"{task}:receipt_missing"],
        }
    receipt = json.loads(path.read_text(encoding="utf-8"))
    failures, _summary = audit_runtime_receipt(receipt, task=task)
    metrics = receipt.get("metrics") or {}
    return {
        "available": True,
        "first_gt_changed_call": _first_gt_changed_call(receipt),
        "release_integrity_failures": failures,
        "executor_calls": metrics.get("executor_api_calls"),
        "bootstrap_calls": metrics.get("bootstrap_api_calls"),
        "submit_attempts": metrics.get("submit_attempts"),
        "submit_holds": metrics.get("submit_holds"),
        "total_gt_context_chars_added": metrics.get("total_gt_context_chars_added"),
    }


def build_regression_forensics(
    baseline: dict[str, Any],
    treatment: dict[str, Any],
    *,
    baseline_trajectory_root: Path | None = None,
    treatment_artifact_root: Path | None = None,
    previous_treatment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    baseline_rows = _rows(baseline)
    treatment_rows = _rows(treatment)
    previous_rows = _rows(previous_treatment or {})
    profile_id = str((treatment.get("manifest") or {}).get("profile_id") or "")
    task_ids = sorted(treatment_rows)
    failures: list[str] = []
    if set(task_ids) - set(baseline_rows):
        failures.append("baseline_rows_missing")
    treatment_digest = str(
        (treatment.get("manifest") or {}).get("task_set_sha256") or ""
    )
    if treatment_digest != task_set_sha256(task_ids):
        failures.append("treatment_task_set_hash_mismatch")

    rows: list[dict[str, Any]] = []
    for task in task_ids:
        before = baseline_rows.get(task) or {}
        after = treatment_rows[task]
        before_solved = before.get("solved") is True
        after_solved = after.get("solved") is True
        outcome = (
            "positive_flip"
            if after_solved and not before_solved
            else "negative_flip"
            if before_solved and not after_solved
            else "stable_solved"
            if before_solved
            else "stable_unsolved"
        )
        receipt_path = _find_task_file(treatment_artifact_root, task, "central_receipt.json")
        receipt = _receipt_summary(receipt_path, task)
        baseline_trajectory = _find_task_file(
            baseline_trajectory_root, task, "miniswe_trajectory.json"
        )
        treatment_trajectory = _find_task_file(
            treatment_artifact_root, task, "miniswe_trajectory.json"
        )
        baseline_actions = _action_hashes(baseline_trajectory)
        treatment_actions = _action_hashes(treatment_trajectory)
        divergence = _first_divergence(baseline_actions, treatment_actions)
        baseline_steps = _trajectory_steps(baseline_trajectory)
        treatment_steps = _trajectory_steps(treatment_trajectory)
        baseline_divergence_step = _step_for_action(baseline_steps, divergence)
        treatment_divergence_step = _step_for_action(treatment_steps, divergence)
        divergence_call = (
            int(treatment_divergence_step.get("call") or 0)
            if treatment_divergence_step is not None
            else None
        )
        divergence_reasoning = str(
            (treatment_divergence_step or {}).get("reasoning_content") or ""
        )
        receipt_document = (
            json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt_path is not None
            else {}
        )
        preceding_deliveries = _delivery_influence(
            receipt_document,
            through_call=divergence_call,
            reasoning=divergence_reasoning,
        )
        first_gt_call = receipt["first_gt_changed_call"]
        if outcome != "negative_flip":
            attribution = "not_a_regression"
            confidence = "high"
        elif not baseline_actions or not treatment_actions:
            attribution = "unknown_missing_trajectory"
            confidence = "unknown"
        elif first_gt_call is None or (divergence is not None and divergence < first_gt_call):
            attribution = "model_sampling_divergence_no_preceding_gt_view_change"
            confidence = "high"
        else:
            attribution = "gt_context_causal_candidate_not_proven"
            confidence = "moderate"
        deltas = {
            field: round(float(after[field]) - float(before[field]), 9)
            for field in RESOURCE_FIELDS
            if isinstance(before.get(field), (int, float))
            and not isinstance(before.get(field), bool)
            and isinstance(after.get(field), (int, float))
            and not isinstance(after.get(field), bool)
        }
        previous = previous_rows.get(task)
        rows.append(
            {
                "task": task,
                "outcome": outcome,
                "baseline_solved": before_solved,
                "treatment_solved": after_solved,
                "previous_treatment_solved": (
                    previous.get("solved") if isinstance(previous, dict) else None
                ),
                "resource_deltas": deltas,
                "baseline_action_count": len(baseline_actions),
                "treatment_action_count": len(treatment_actions),
                "baseline_exit_status": _exit_status(baseline_trajectory),
                "treatment_exit_status": _exit_status(treatment_trajectory),
                "first_action_divergence": divergence,
                "first_divergence_detail": {
                    "treatment_call": divergence_call,
                    "baseline_command": _command_at(baseline_steps, divergence),
                    "treatment_command": _command_at(treatment_steps, divergence),
                    "baseline_reasoning": str(
                        (baseline_divergence_step or {}).get("reasoning_content") or ""
                    ),
                    "treatment_reasoning": divergence_reasoning,
                    "preceding_gt_deliveries": preceding_deliveries,
                    "reasoning_uptake_is_proxy_not_causal_proof": True,
                },
                "first_gt_provider_view_change": first_gt_call,
                "attribution": attribution,
                "confidence": confidence,
                "receipt": receipt,
            }
        )
    return {
        "schema": "gt.tb2.regression_forensics.v2",
        "profile_id": profile_id,
        "task_set_sha256": task_set_sha256(task_ids),
        "passed": not failures,
        "failures": failures,
        "negative_flips": [row["task"] for row in rows if row["outcome"] == "negative_flip"],
        "positive_flips": [row["task"] for row in rows if row["outcome"] == "positive_flip"],
        "rows": rows,
        "integrity_boundary": (
            "Uses only frozen outcome/resource rows, agent trajectories, and central receipts; "
            "never verifier tests, reference solutions, reward files, or verifier output."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--treatment", type=Path, required=True)
    parser.add_argument("--baseline-trajectories", type=Path)
    parser.add_argument("--treatment-artifacts", type=Path)
    parser.add_argument("--previous-treatment", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_regression_forensics(
        json.loads(args.baseline.read_text(encoding="utf-8")),
        json.loads(args.treatment.read_text(encoding="utf-8")),
        baseline_trajectory_root=args.baseline_trajectories,
        treatment_artifact_root=args.treatment_artifacts,
        previous_treatment=(
            json.loads(args.previous_treatment.read_text(encoding="utf-8"))
            if args.previous_treatment
            else None
        ),
    )
    payload = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
