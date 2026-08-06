from __future__ import annotations

import json

from gt_engine.deep_metrics import compare_arms, extract_trajectory, render_delta_markdown


def _assistant(command: str, *, prompt: int, completion: int, cached: int = 0) -> dict:
    return {
        "role": "assistant",
        "content": f"run {command}",
        "extra": {
            "actions": [{"command": command, "tool_call_id": command}],
            "response": {
                "usage": {
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "prompt_cache_hit_tokens": cached,
                    "prompt_cache_miss_tokens": prompt - cached,
                }
            },
            "cost": 0.25,
        },
    }


def test_extract_trajectory_uses_identical_deep_metrics_for_any_arm(tmp_path):
    path = tmp_path / "task_trajectory.json"
    path.write_text(
        json.dumps(
            {
                "info": {"exit_status": "Submitted"},
                "messages": [
                    {"role": "user", "content": "fix it"},
                    _assistant("rg -n bug .", prompt=100, completion=10, cached=60),
                    {"role": "tool", "tool_call_id": "rg -n bug .", "extra": {"returncode": 0}},
                    _assistant("pytest -q", prompt=120, completion=12, cached=80),
                    {"role": "tool", "tool_call_id": "pytest -q", "extra": {"returncode": 1}},
                    _assistant("pytest -q", prompt=130, completion=8, cached=90),
                    {"role": "tool", "tool_call_id": "pytest -q", "extra": {"returncode": 0}},
                ],
            }
        ),
        encoding="utf-8",
    )

    metrics = extract_trajectory(path, task="task", reward=1)

    assert metrics["input_tokens"] == 350
    assert metrics["output_tokens"] == 30
    assert metrics["cache_tokens"] == 230
    assert metrics["uncached_input_tokens"] == 120
    assert metrics["normalized_cost_usd"] > 0
    assert metrics["api_calls"] == 3
    assert metrics["actions"] == 3
    assert metrics["check_actions"] == 2
    assert metrics["failed_actions"] == 1
    assert metrics["repeated_commands"] == 1
    assert metrics["wasted_action_proxy"] == 2
    assert metrics["reward"] == 1
    assert metrics["solved"] is True


def test_compare_arms_rejects_solve_regression_censoring_and_positive_resources():
    baseline = {
        "task": {
            "solved": True,
            "censored": False,
            "total_tokens": 100,
            "api_calls": 10,
            "actions": 10,
            "assistant_steps": 10,
            "normalized_cost_usd": 1.0,
        }
    }
    efficient = {
        "task": {
            "solved": True,
            "censored": False,
            "total_tokens": 90,
            "api_calls": 9,
            "actions": 9,
            "assistant_steps": 9,
            "normalized_cost_usd": 0.9,
        }
    }
    positive = {"task": {**efficient["task"], "actions": 11}}
    regressed = {"task": {**efficient["task"], "solved": False}}
    censored = {"task": {**efficient["task"], "censored": True}}

    assert compare_arms(baseline, efficient)["gate_passed"] is True
    assert compare_arms(baseline, positive)["gate_passed"] is False
    assert compare_arms(baseline, regressed)["solve_regressions"] == ["task"]
    assert compare_arms(baseline, censored)["censored_treatment"] == ["task"]


def test_compare_arms_reports_deep_behavior_context_and_timing_deltas():
    baseline = {
        "task": {
            "solved": True,
            "censored": False,
            "total_tokens": 100,
            "api_calls": 10,
            "actions": 10,
            "assistant_steps": 10,
            "normalized_cost_usd": 1.0,
            "uncached_input_tokens": 40,
            "context_chars_sent": 500,
            "failed_actions": 3,
            "wasted_action_proxy": 4,
            "steps_to_submit": 10,
            "gt_context_chars_added": 0,
            "timely_payload_deliveries": 0,
            "late_payload_deliveries": 0,
        }
    }
    treatment = {
        "task": {
            **baseline["task"],
            "total_tokens": 90,
            "uncached_input_tokens": 30,
            "context_chars_sent": 450,
            "failed_actions": 1,
            "wasted_action_proxy": 1,
            "steps_to_submit": 8,
            "gt_context_chars_added": 70,
            "timely_payload_deliveries": 2,
        }
    }

    comparison = compare_arms(baseline, treatment)
    diagnostics = comparison["tasks"]["task"]["diagnostic_deltas"]

    assert diagnostics["uncached_input_tokens"] == -10
    assert diagnostics["context_chars_sent"] == -50
    assert diagnostics["failed_actions"] == -2
    assert diagnostics["wasted_action_proxy"] == -3
    assert diagnostics["steps_to_submit"] == -2
    assert diagnostics["gt_context_chars_added"] == 70
    assert diagnostics["timely_payload_deliveries"] == 2
    assert comparison["aggregate_deltas"]["context_chars_sent"] == -50
    markdown = render_delta_markdown("baseline_to_treatment", comparison)
    assert "Deep behavior/context deltas" in markdown
    assert "uncached" in markdown
    assert "late payloads" in markdown


def test_extract_trajectory_reports_receipt_context_attribution(tmp_path):
    trajectory = tmp_path / "task_trajectory.json"
    trajectory.write_text(
        json.dumps({"messages": [_assistant("pytest -q", prompt=10, completion=1)]})
    )
    receipt = tmp_path / "central_receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "features": {},
                "metrics": {
                    "context_compiler_calls": 2,
                    "context_fact_candidates": 7,
                    "context_facts_represented": 4,
                    "context_facts_selected": 1,
                    "context_facts_controller_only": 2,
                    "context_facts_omitted": 2,
                    "context_facts_accounted": 7,
                    "context_unique_reasoning_chars_removed": 0,
                    "context_compiler_effects_considered": 5,
                    "context_compiler_effects_unaccounted": 0,
                    "preflight_known_segment_operations": 3,
                    "preflight_unknown_segment_operations": 1,
                },
                "model_call_contexts": [
                    {"stock_context_chars": 100, "runtime_advisory_chars": 0, "context_chars": 100},
                    {
                        "stock_context_chars": 150,
                        "runtime_advisory_chars": 80,
                        "context_chars": 230,
                    },
                ],
            }
        )
    )

    metrics = extract_trajectory(trajectory, task="task", receipt_path=receipt)

    assert metrics["runtime_advisory_context_chars"] == 80
    assert metrics["stock_context_chars_from_receipt"] == 250
    assert metrics["max_context_chars_from_receipt"] == 230
    assert metrics["context_compiler_calls"] == 2
    assert metrics["context_fact_candidates"] == 7
    assert metrics["context_facts_accounted"] == 7
    assert metrics["context_unique_reasoning_chars_removed"] == 0
    assert metrics["context_compiler_effects_considered"] == 5
    assert metrics["context_compiler_effects_unaccounted"] == 0
    assert metrics["preflight_known_segment_operations"] == 3


def test_feature_funnel_counts_deliveries_and_alignment(tmp_path):
    trajectory = tmp_path / "task_trajectory.json"
    trajectory.write_text(
        json.dumps(
            {
                "messages": [
                    {"role": "user", "content": "fix it"},
                    _assistant("write app.py", prompt=10, completion=1),
                    _assistant("pytest app.py", prompt=10, completion=1),
                ],
            }
        )
    )
    receipt = tmp_path / "central_receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "features": {
                    "produced_counts": {"syntax_result": 1},
                    "guidance_suppressed": 2,
                    "effects": [{"applied_after_action": 1}],
                    "receipts": [
                        {
                            "feature_id": "syntax_result",
                            "action": 1,
                            "model_visible": True,
                            "payload": {
                                "path": "app.py",
                                "command": "python3 -m py_compile app.py",
                            },
                        }
                    ],
                },
                "guidance_deliveries": [
                    {"feature_id": "syntax_result", "evidence_action": 1}
                ],
            }
        )
    )

    metrics = extract_trajectory(trajectory, task="task", receipt_path=receipt)

    assert metrics["feature_produced"] == 1
    assert metrics["feature_consumed"] == 1
    assert metrics["feature_effects_applied"] == 1
    assert metrics["guidance_deliveries"] == 1
    assert metrics["guidance_behaviorally_aligned"] == 1
    assert metrics["guidance_suppressed"] == 2
    assert "guidance_l1_delivered" not in metrics
    assert "guidance_l3_acted" not in metrics
