from __future__ import annotations

import json

from gt_engine.deep_metrics import compare_arms, extract_trajectory


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
