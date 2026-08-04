"""Provider-free replay of archived GT-on trajectories through the repaired policy.

Replays each archived task's action stream through the repaired
``CentralFeatureRuntime`` and a fresh evidence ledger, then compares the
repaired behavior against the archived receipt.  This is the Phase 9 gate:
no paid run is allowed until the per-task outcomes are reviewed.

The archived receipts are v2 (produced before this repair); the replay is the
only place the repaired policy is exercised against real trajectories without
a provider.  Workspace transitions are reconstructed from the archived
``GT_CHANGE_SURFACE`` receipts, so change classification exercises the new
source-revision model on the same paths the smoke actually touched.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from gt_engine.central_runtime import (
    CENTRAL_FEATURE_IDS,
    CentralFeatureRuntime,
    EvidenceLedger,
    WorkspaceTransition,
    classify_change,
    classify_validation_command,
    explicit_check_commands,
    task_deliverable_paths,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _instruction(trajectory: dict[str, Any]) -> str:
    for message in trajectory.get("messages") or []:
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _iter_events(trajectory: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one event per executed action with command, returncode, output."""
    tool_results: dict[str, list[dict[str, Any]]] = {}
    for message in trajectory.get("messages") or []:
        if message.get("role") == "tool":
            tool_results.setdefault(str(message.get("tool_call_id") or ""), []).append(message)
    cursors: dict[str, int] = {}
    events: list[dict[str, Any]] = []
    index = 0
    for message in trajectory.get("messages") or []:
        if message.get("role") != "assistant":
            continue
        for action in (message.get("extra") or {}).get("actions") or []:
            index += 1
            command = str(action.get("command") or "")
            tool_id = str(action.get("tool_call_id") or "")
            results = tool_results.get(tool_id) or []
            cursor = cursors.get(tool_id, 0)
            tool_message = results[cursor] if cursor < len(results) else None
            cursors[tool_id] = cursor + 1
            extra = (tool_message or {}).get("extra") or {}
            returncode = extra.get("returncode")
            if returncode is None:
                returncode = -1
            output = str(extra.get("raw_output") or (tool_message or {}).get("content") or "")
            events.append(
                {"index": index, "command": command, "returncode": returncode, "output": output}
            )
    return events


def _archived_transitions(receipt: dict[str, Any]) -> dict[int, dict[str, tuple[str, ...]]]:
    by_action: dict[int, dict[str, tuple[str, ...]]] = {}
    for row in (receipt.get("features") or {}).get("receipts") or []:
        if row.get("feature_id") != "GT_CHANGE_SURFACE":
            continue
        payload = row.get("payload") or {}
        by_action[int(row.get("action") or 0)] = {
            "created": tuple(payload.get("created") or ()),
            "modified": tuple(payload.get("modified") or ()),
            "deleted": tuple(payload.get("deleted") or ()),
        }
    return by_action


def replay_task(trajectory_path: Path, receipt_path: Path, task_name: str) -> dict[str, Any]:
    trajectory = _load_json(trajectory_path)
    receipt = _load_json(receipt_path)
    instruction = _instruction(trajectory)
    checks = explicit_check_commands(instruction)
    deliverables = task_deliverable_paths(instruction)
    events = _iter_events(trajectory)
    transitions = _archived_transitions(receipt)

    runtime = CentralFeatureRuntime(model_visible=True)
    runtime.begin_task(
        instruction,
        revision="replay-w0",
        source_revision="replay-s0",
        explicit_checks=checks,
        task_deliverables=deliverables,
    )
    ledger = EvidenceLedger(max_holds=1)
    source_revision = "replay-s0"
    source_epoch = 0
    artifact_debt_triggers: list[dict[str, str]] = []

    for event in events:
        action_id = event["index"]
        change = transitions.get(action_id)
        transition = WorkspaceTransition(
            action_id,
            event["command"],
            "replay-w0",
            "replay-w0",
            created=change["created"] if change else (),
            modified=change["modified"] if change else (),
            deleted=change["deleted"] if change else (),
        )
        authored = [
            path
            for path in transition.changed_paths
            if classify_change(path, kind="f", task_deliverables=deliverables).validation_relevant
        ]
        if authored:
            source_epoch += 1
            source_revision = f"replay-s{source_epoch}"
        classification = classify_validation_command(event["command"], checks).with_result(
            result_code=event["returncode"],
            output=event["output"],
            source_revision=source_revision,
            workspace_revision="replay-w0",
        )
        runtime.observe_action(
            action_id=action_id,
            command=event["command"],
            output=event["output"],
            returncode=event["returncode"],
            transition=transition,
            revision="replay-w0",
            source_revision=source_revision,
            validation=classification,
        )
        if classification.is_validation:
            ledger.record_check(
                event["command"],
                returncode=event["returncode"],
                revision=source_revision,
                grounded=classification.grounded,
                classification=classification,
            )

    summary = runtime.summary()
    for row in summary["receipts"]:
        if row["feature_id"] != "GT_EDIT_CHECK":
            continue
        if row["payload"].get("intervention") != "validation_debt":
            continue
        for path in row["payload"].get("changed_paths") or []:
            change = classify_change(path, kind="f", task_deliverables=deliverables)
            if not change.validation_relevant:
                artifact_debt_triggers.append({"path": path, "origin": change.origin.value})

    runtime.model_feedback()
    readiness = ledger.readiness_evidence(source_revision)
    ledger_declared = sorted(
        {
            item.command
            for item in ledger.outcomes.values()
            if item.grounded and item.command_class == "declared_validation"
        }
    )
    ledger_checks_total = sum(
        1 for item in ledger.outcomes.values() if item.grounded
    )

    old_features = receipt.get("features") or {}
    old_receipts = old_features.get("receipts") or []
    old_cert = next(
        (row for row in old_receipts if row.get("feature_id") == "GT_CERT_DELIVERY"), None
    )
    old_produced = old_features.get("produced_counts")
    if old_produced is None:
        old_produced = Counter(row.get("feature_id") for row in old_receipts)
    old_deliveries = receipt.get("guidance_deliveries") or []

    return {
        "task": task_name,
        "actions": len(events),
        "source_epoch": source_epoch,
        "explicit_checks": list(checks),
        "deliverables": list(deliverables),
        "old": {
            "produced": int(sum(old_produced.values())),
            "produced_features": {
                feature_id: int(old_produced.get(feature_id) or 0)
                for feature_id in CENTRAL_FEATURE_IDS
                if old_produced.get(feature_id)
            },
            "guidance_deliveries": len(old_deliveries),
            "guidance_chars": int(old_features.get("guidance_chars") or 0),
            "certificate": (old_cert or {}).get("payload") or {},
            "exit_status": str((trajectory.get("info") or {}).get("exit_status") or ""),
        },
        "new": {
            "produced": sum(summary["produced_counts"].values()),
            "produced_features": {
                feature_id: count
                for feature_id, count in summary["produced_counts"].items()
                if count
            },
            "guidance_events": summary["guidance_events"],
            "guidance_chars": summary["guidance_chars"],
            "validation_declared": sum(
                1
                for row in summary["validation_log"]
                if row["command_class"] == "declared_validation"
            ),
            "validation_recognized": sum(
                1
                for row in summary["validation_log"]
                if row["command_class"] == "recognized_validation"
            ),
            "certificate": {
                "check_count": len(readiness),
                "passing_checks": sum(item.returncode == 0 for item in readiness),
                "failing_checks": sum(item.returncode != 0 for item in readiness),
            },
            "ledger_checks_total": ledger_checks_total,
            "ledger_declared_checks": ledger_declared,
            "artifact_debt_triggers": artifact_debt_triggers,
            "consumer_features": sorted(summary["consumer_paths"]),
        },
    }


def _outcomes(task: dict[str, Any]) -> list[str]:
    failed: list[str] = []
    if task["new"]["artifact_debt_triggers"]:
        failed.append(
            f"artifact-driven validation debt: {task['new']['artifact_debt_triggers']}"
        )
    new_declared = int(task["new"]["validation_declared"])
    ledger_total = int(task["new"]["ledger_checks_total"])
    if new_declared > 0 and ledger_total == 0:
        failed.append("runtime classified declared validations but the ledger recorded none")
    old_cert_count = int((task["old"].get("certificate") or {}).get("check_count") or 0)
    if old_cert_count > 0 and ledger_total == 0:
        failed.append("old certificate checks were lost by the repaired policy")
    if task["new"]["guidance_events"] > int(task["old"]["guidance_deliveries"]) + 2:
        failed.append("external guidance growth without a new grounded effect")
    return failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    tasks: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    for trajectory_path in sorted(args.run_dir.rglob("agent/miniswe_trajectory.json")):
        receipt_path = trajectory_path.parent / "central_receipt.json"
        if not receipt_path.exists():
            issues.append(f"{trajectory_path}: missing central_receipt.json")
            continue
        task_name = trajectory_path.parent.parent.parent.name.split("__")[0]
        tasks[task_name] = replay_task(trajectory_path, receipt_path, task_name)

    report = {"version": "gt.central_replay.v1", "task_count": len(tasks), "tasks": tasks}
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.json:
        args.json.write_text(rendered + "\n", encoding="utf-8")

    print(f"replayed {len(tasks)} task(s)")
    for task_name, task in tasks.items():
        failures = _outcomes(task)
        status = "PASS" if not failures else "FAIL"
        print(
            f"  {status} {task_name}: actions={task['actions']} "
            f"old_produced={task['old']['produced']} new_produced={task['new']['produced']} "
            f"old_deliveries={task['old']['guidance_deliveries']} "
            f"new_guidance={task['new']['guidance_events']} "
            f"old_cert={task['old']['certificate'].get('check_count')} "
            f"new_cert={task['new']['certificate']['check_count']} "
            f"debt_triggers={len(task['new']['artifact_debt_triggers'])}"
        )
        for failure in failures:
            print(f"    ! {task_name}: {failure}")
    for issue in issues:
        print(f"  !! {issue}")

    ok = bool(tasks) and not issues and all(not _outcomes(task) for task in tasks.values())
    print("REPLAY_OK" if ok else "REPLAY_FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
