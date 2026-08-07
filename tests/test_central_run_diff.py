"""Provider-free comparison contract for two archived central-runtime runs."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.central_run_diff import compare_run_roots


def _write_run(
    root: Path,
    *,
    actions: list[str],
    request_hashes: list[str],
    delivery_call: int | None = None,
) -> None:
    agent = root / "artifact-task-demo" / "demo__trial" / "agent"
    agent.mkdir(parents=True)
    messages: list[dict] = [{"role": "user", "content": "Solve demo."}]
    for command in actions:
        messages.append(
            {
                "role": "assistant",
                "content": "act",
                "extra": {"actions": [{"command": command}]},
            }
        )
    (agent / "miniswe_trajectory.json").write_text(
        json.dumps({"messages": messages}), encoding="utf-8"
    )
    receipt = {
        "model_call_contexts": [
            {
                "call": index,
                "provider_messages_sha256": request_hash,
                "request_payload_sha256": f"payload-{request_hash}",
                "provider_message_count": 2,
                "provider_view_compacted": index > 1,
                "provider_view_elided_chars": 10 if index > 1 else 0,
            }
            for index, request_hash in enumerate(request_hashes, start=1)
        ],
        "guidance_deliveries": (
            [
                {
                    "feature_id": "GT_EDIT_CHECK",
                    "evidence_action": delivery_call - 1,
                    "first_eligible_call": delivery_call,
                    "delivered_before_call": delivery_call,
                    "request_payload_sha256": f"payload-{request_hashes[delivery_call - 1]}",
                    "chars": 12,
                }
            ]
            if delivery_call
            else []
        ),
        "metrics": {
            "preflight_calls": len(actions),
            "preflight_applied_dispositions": {"pass": len(actions)},
            "context_compactions": max(0, len(request_hashes) - 1),
            "context_chars_elided": max(0, len(request_hashes) - 1) * 10,
            "total_gt_context_chars_added": 12 if delivery_call else 0,
            "effective_actions": len(actions),
        },
        "features": {"semantic_decisions": {"frames": []}},
    }
    (agent / "central_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")


def test_run_diff_attributes_first_action_divergence_before_visible_evidence(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    _write_run(
        left,
        actions=["ls -la", "cat app.py"],
        request_hashes=["same-first", "left-second"],
        delivery_call=2,
    )
    _write_run(
        right,
        actions=["pwd", "cat app.py"],
        request_hashes=["same-first", "right-second"],
        delivery_call=2,
    )

    report = compare_run_roots(left, right)
    task = report["tasks"]["demo"]

    assert task["first_divergent_model_call"] == 1
    assert task["first_divergence_precedes_visible_evidence"] is True
    assert task["request_differences"] == [2]
    assert task["guidance"]["left_first_visible_call"] == 2
    assert task["guidance"]["right_first_visible_call"] == 2


def test_run_diff_reports_identical_execution_without_spurious_differences(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    for root in (left, right):
        _write_run(
            root,
            actions=["ls -la", "cat app.py"],
            request_hashes=["same-first", "same-second"],
        )

    report = compare_run_roots(left, right)
    task = report["tasks"]["demo"]

    assert task["first_divergent_model_call"] is None
    assert task["request_differences"] == []
    assert task["accounting_complete"] is True


def test_central_replay_direct_script_invocation_bootstraps_project_imports():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "central_replay.py"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Provider-free replay" in result.stdout
