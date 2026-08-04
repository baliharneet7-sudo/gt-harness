"""Provider-free replay harness contract tests."""

from __future__ import annotations

import json

from scripts.central_replay import _outcomes, replay_task


def _trajectory(actions, instruction="Fix it, then run `pytest -q`.") -> dict:
    messages = [{"role": "user", "content": instruction}]
    for index, (command, rc) in enumerate(actions):
        tool_id = f"call-{index}"
        messages.append(
            {
                "role": "assistant",
                "content": "act",
                "extra": {
                    "actions": [{"command": command, "tool_call_id": tool_id}],
                    "response": {"usage": {}},
                },
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_id,
                "content": "output",
                "extra": {"returncode": rc, "raw_output": "out"},
            }
        )
    return {"info": {"exit_status": "Submitted"}, "messages": messages}


def _receipt(gt_change_surfaces=None) -> dict:
    rows = [
        {
            "feature_id": "GT_CERT_DELIVERY",
            "action": 10,
            "payload": {
                "check_count": 0,
                "passing_checks": 0,
                "failing_checks": 0,
                "readiness": "unverified",
            },
        }
    ]
    for action, paths in (gt_change_surfaces or {}).items():
        rows.append(
            {
                "feature_id": "GT_CHANGE_SURFACE",
                "action": action,
                "payload": {
                    "created": list(paths.get("created", ())),
                    "modified": list(paths.get("modified", ())),
                    "deleted": list(paths.get("deleted", ())),
                },
            }
        )
    return {"features": {"receipts": rows}, "guidance_deliveries": []}


def test_replay_records_declared_validation_in_the_ledger(tmp_path):
    trajectory = _trajectory([("write app.py", 0), ("pytest -q", 0)])
    trajectory_path = tmp_path / "miniswe_trajectory.json"
    trajectory_path.write_text(json.dumps(trajectory), encoding="utf-8")
    receipt_path = tmp_path / "central_receipt.json"
    receipt_path.write_text(json.dumps(_receipt()), encoding="utf-8")

    report = replay_task(trajectory_path, receipt_path, "task")

    assert report["new"]["validation_declared"] == 1
    assert report["new"]["ledger_checks_total"] == 1
    assert report["new"]["certificate"]["passing_checks"] == 1
    assert report["new"]["artifact_debt_triggers"] == []
    assert _outcomes(report) == []


def test_replay_flags_artifact_driven_validation_debt(tmp_path):
    trajectory = _trajectory(
        [
            ("write benchmark_out.txt", 0),
            ("write app.py", 0),
            ("write app.py", 0),
            ("write app.py", 0),
        ],
        instruction="Update it, then run `pytest -q`.",
    )
    trajectory_path = tmp_path / "miniswe_trajectory.json"
    trajectory_path.write_text(json.dumps(trajectory), encoding="utf-8")
    receipt_path = tmp_path / "central_receipt.json"
    receipt_path.write_text(json.dumps(_receipt()), encoding="utf-8")

    report = replay_task(trajectory_path, receipt_path, "task")

    assert _outcomes(report) == []


def test_replay_detects_old_certificate_loss(tmp_path):
    trajectory = _trajectory([("pwd", 0)], instruction="Just work.")
    trajectory_path = tmp_path / "miniswe_trajectory.json"
    trajectory_path.write_text(json.dumps(trajectory), encoding="utf-8")
    receipt_path = tmp_path / "central_receipt.json"
    receipt = _receipt()
    cert = next(
        row for row in receipt["features"]["receipts"] if row["feature_id"] == "GT_CERT_DELIVERY"
    )
    cert["payload"]["check_count"] = 3
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    report = replay_task(trajectory_path, receipt_path, "task")

    assert "old certificate checks were lost" in " ".join(_outcomes(report))
