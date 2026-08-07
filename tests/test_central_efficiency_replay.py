from __future__ import annotations

import json

from scripts.central_efficiency_replay import replay_run


def _write_trial(root, task, *, instruction, command, declared, partial, headroom):
    agent = root / f"{task}__trial" / "agent"
    agent.mkdir(parents=True)
    (agent / "miniswe_trajectory.json").write_text(
        json.dumps({"messages": [{"role": "user", "content": instruction}]}),
        encoding="utf-8",
    )
    (agent / "central_receipt.json").write_text(
        json.dumps(
            {
                "features": {
                    "validation_log": [{"action": 1, "command": command}],
                    "receipts": [
                        {
                            "feature_id": "covering_red",
                            "action": 1,
                            "boundary": "test_result",
                            "model_visible": True,
                        },
                        {
                            "feature_id": "submit_refusal",
                            "action": 1,
                            "boundary": "test_result",
                            "model_visible": True,
                        },
                    ],
                },
                "metrics": {
                    "completion_plan_status": "partial" if partial else "complete",
                    "completion_probe_execs": 3,
                },
                "model_call_contexts": [
                    {
                        "request_budget": {
                            "context_limit_tokens": 1_048_576,
                            "counted_tokens": 1,
                            "conservative_tokens": 1,
                            "effective_tokens": 1,
                            "hard_prompt_limit": 943_718,
                            "remaining_tokens": headroom,
                            "counter_source": "fixture",
                        }
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_archived_replay_projects_custom_failures_private_and_partial_probes_zero(tmp_path):
    _write_trial(
        tmp_path,
        "custom",
        instruction="Demonstrate the behavior.",
        command="python3 /tmp/test_single.py",
        declared=False,
        partial=True,
        headroom=400_000,
    )
    _write_trial(
        tmp_path,
        "declared",
        instruction="Run `pytest -q`.",
        command="pytest -q",
        declared=True,
        partial=False,
        headroom=400_000,
    )

    result = replay_run(tmp_path)

    assert result["invalid_visible_failure_receipts"] == 2
    assert result["invalid_visible_failure_actions"] == 1
    assert result["projected_partial_completion_probe_execs"] == 0
    assert result["avoided_partial_completion_probe_execs"] == 3
    assert result["projected_compaction_epochs"] == 0
    assert result["declared_visible_failure_receipts_preserved"] == 2
    assert all(
        row["minimum_provider_headroom_tokens"] == 400_000
        for row in result["tasks"].values()
    )
    assert all(
        row["provider_budget_evidence"] == "recorded_transformed_request"
        for row in result["tasks"].values()
    )
