#!/usr/bin/env python3
"""Write the minimal, truthful task-truth record for the GT-OFF arm.

The GT-OFF control has no GT runtime ledger, graph certificate, or feature
delivery.  It still needs the same task-truth schema so the common metrics
collector can audit a real trajectory and evaluator verdict without importing
GT-ON-only modules.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def build(task_dir: Path, instance_id: str) -> dict[str, Any]:
    trajectory_path = task_dir / "mini-swe-agent.trajectory.json"
    trajectory = _load(trajectory_path)
    messages = trajectory.get("messages") if isinstance(trajectory.get("messages"), list) else []
    info = trajectory.get("info") if isinstance(trajectory.get("info"), dict) else {}
    stats = info.get("model_stats") if isinstance(info.get("model_stats"), dict) else {}
    report = _load(task_dir / "report.json")
    reward = None
    reward_path = task_dir / "reward.txt"
    try:
        reward = float(reward_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        verifier = report.get("verifier_result")
        if isinstance(verifier, dict):
            rewards = verifier.get("rewards")
            if isinstance(rewards, dict) and isinstance(rewards.get("reward"), (int, float)):
                reward = float(rewards["reward"])
    resolved = bool(reward is not None and reward >= 1.0)
    turns = int(stats.get("api_calls") or 0)
    if turns <= 0:
        turns = sum(
            1 for message in messages
            if isinstance(message, dict)
            and (message.get("role") == "assistant" or isinstance(message.get("output"), list))
        )
    return {
        "schema": "gt.task_truth.v1",
        "authority": {
            "outcome": "evaluator report/reward.txt",
            "trajectory": "mini-swe-agent.trajectory.json",
            "gt": "not_applicable_gt_off",
        },
        "instance_id": instance_id,
        "baseline_gt_off": True,
        "certs": {},
        "runtime_witness": {
            "gt_prebuilt_active": False,
            "hook_hash_match": None,
            "gt_meta_present": False,
            "cert_fail_reconciled": None,
        },
        "outcome": {
            "reward": reward,
            "resolved": resolved,
            "failure_class": "RESOLVED" if resolved else "AGENT",
            "infra_subtype": None,
            "in_resolved_denominator": True,
        },
        "deep_metrics": {},
        "trajectory_state": {
            "turns_observed": turns,
            "source": "mini-swe-agent.trajectory.json",
        },
        "trajectory_integrity": {
            "mini_path": str(trajectory_path),
            "mini_bytes": trajectory_path.stat().st_size if trajectory_path.is_file() else 0,
        },
        "runtime_control": {
            "enforcement_semantics": "gt_off",
            "consumption_summary": {"schema": "gt.consumption_ledger.v2", "entries": []},
        },
        "gt_delivery": {
            "mode": "off",
            "deliveries": 0,
            "consumed": 0,
        },
    }


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit("usage: baseline_task_truth.py TASK_DIR OUTPUT [INSTANCE_ID]")
    task_dir = Path(sys.argv[1])
    output = Path(sys.argv[2])
    instance_id = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("GT_INSTANCE_ID", task_dir.name)
    output.write_text(json.dumps(build(task_dir, instance_id), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
