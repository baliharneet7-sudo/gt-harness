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


def test_extract_trajectory_includes_outer_harbor_timeout_and_wall_time(tmp_path):
    path = tmp_path / "task_trajectory.json"
    path.write_text(
        json.dumps(
            {
                "info": {"exit_status": ""},
                "messages": [_assistant("pytest -q", prompt=100, completion=10)],
            }
        ),
        encoding="utf-8",
    )
    harbor_result = {
        "task_name": "task",
        "agent_execution": {
            "started_at": "2026-08-06T01:00:00Z",
            "finished_at": "2026-08-06T01:15:00Z",
        },
        "started_at": "2026-08-06T00:59:00Z",
        "finished_at": "2026-08-06T01:16:00Z",
        "exception_info": {"exception_type": "AgentTimeoutError"},
    }

    metrics = extract_trajectory(path, task="task", reward=1, harbor_result=harbor_result)

    assert metrics["censored"] is True
    assert metrics["censored_reason"] == "AgentTimeoutError"
    assert metrics["official_solved"] is True
    assert metrics["uncensored_resolved"] is False
    assert metrics["solved"] is False
    assert metrics["agent_wall_time_seconds"] == 900.0
    assert metrics["trial_wall_time_seconds"] == 1020.0


def test_context_window_provider_exception_is_censored(tmp_path):
    path = tmp_path / "task_trajectory.json"
    path.write_text(
        json.dumps(
            {
                "info": {"exit_status": "ContextWindowExceededError"},
                "messages": [_assistant("sed -n '1,20p' src/main.py", prompt=10, completion=1)],
            }
        ),
        encoding="utf-8",
    )
    harbor_result = {
        "task_name": "task",
        "exception_info": {"exception_type": "ContextWindowExceededError"},
    }

    metrics = extract_trajectory(path, task="task", reward=1, harbor_result=harbor_result)

    assert metrics["official_solved"] is True
    assert metrics["censored"] is True
    assert metrics["censored_reason"] == "ContextWindowExceededError"
    assert metrics["uncensored_resolved"] is False
    assert metrics["solved"] is False


def test_rewarded_clean_step_exhaustion_is_salvaged_resolved_not_censored(tmp_path):
    path = tmp_path / "task_trajectory.json"
    path.write_text(
        json.dumps(
            {
                "info": {"exit_status": "LimitsExceeded"},
                "messages": [_assistant("pytest -q", prompt=10, completion=1)],
            }
        ),
        encoding="utf-8",
    )
    harbor_result = {"task_name": "task", "exception_info": None}

    metrics = extract_trajectory(path, task="task", reward=1, harbor_result=harbor_result)

    assert metrics["official_solved"] is True
    assert metrics["censored"] is False
    assert metrics["uncensored_resolved"] is True
    assert metrics["solved"] is True
    assert metrics["solver_exhausted"] is True


def test_compare_arms_rejects_solve_regression_censoring_and_positive_resources():
    baseline = {
        "task": {
            "solved": True,
            "official_solved": True,
            "uncensored_resolved": True,
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
    assert compare_arms(baseline, efficient)["outcomes"] == {
        "baseline_official_resolved": 1,
        "treatment_official_resolved": 1,
        "baseline_uncensored_resolved": 1,
        "treatment_uncensored_resolved": 1,
    }


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


def test_outcome_first_gate_allows_small_per_task_variance_only_when_aggregate_wins():
    baseline = {
        task: {
            "solved": True,
            "censored": False,
            "total_tokens": 100,
            "api_calls": 10,
            "actions": 10,
            "effective_actions": 10,
            "assistant_steps": 10,
            "normalized_cost_usd": 1.0,
            "agent_wall_time_seconds": 100,
        }
        for task in ("a", "b")
    }
    treatment = {
        "a": {
            **baseline["a"],
            "total_tokens": 105,
            "api_calls": 11,
            "actions": 11,
            "effective_actions": 11,
            "normalized_cost_usd": 1.01,
        },
        "b": {
            **baseline["b"],
            "total_tokens": 70,
            "api_calls": 6,
            "actions": 6,
            "effective_actions": 6,
            "normalized_cost_usd": 0.70,
        },
    }

    comparison = compare_arms(baseline, treatment)

    assert comparison["pareto_failures"] == ["a"]
    assert comparison["per_task_bound_failures"] == []
    assert comparison["aggregate_gate_failures"] == []
    assert comparison["gate_passed"] is True


def test_outcome_first_gate_rejects_two_large_per_task_resource_regressions():
    baseline = {
        "a": {
            "solved": True,
            "censored": False,
            "total_tokens": 100,
            "api_calls": 10,
            "actions": 10,
            "effective_actions": 10,
            "assistant_steps": 10,
            "normalized_cost_usd": 1.0,
        },
        "b": {
            "solved": True,
            "censored": False,
            "total_tokens": 1000,
            "api_calls": 100,
            "actions": 100,
            "effective_actions": 100,
            "assistant_steps": 100,
            "normalized_cost_usd": 10.0,
        },
    }
    treatment = {
        "a": {
            **baseline["a"],
            "total_tokens": 150,
            "api_calls": 15,
            "actions": 15,
            "effective_actions": 15,
            "normalized_cost_usd": 1.40,
        },
        "b": {
            **baseline["b"],
            "total_tokens": 700,
            "api_calls": 70,
            "actions": 70,
            "effective_actions": 70,
            "normalized_cost_usd": 7.0,
        },
    }

    comparison = compare_arms(baseline, treatment)

    assert comparison["aggregate_gate_failures"] == []
    assert comparison["per_task_bound_failures"] == ["a"]
    assert comparison["gate_passed"] is False


def test_outcome_gate_rejects_repository_intelligence_failure_even_if_resources_win():
    baseline = {
        "task": {
            "solved": True,
            "censored": False,
            "total_tokens": 100,
            "api_calls": 10,
            "actions": 10,
            "effective_actions": 10,
            "assistant_steps": 10,
            "normalized_cost_usd": 1.0,
        }
    }
    treatment = {
        "task": {
            **baseline["task"],
            "total_tokens": 50,
            "api_calls": 5,
            "actions": 5,
            "effective_actions": 5,
            "assistant_steps": 5,
            "normalized_cost_usd": 0.5,
            "repository_intelligence_required": True,
            "repository_intelligence_status": "failed",
            "repository_intelligence_valid": 0,
        }
    }

    comparison = compare_arms(baseline, treatment)

    assert comparison["invalid_treatments"] == ["task"]
    assert comparison["aggregate_gate_failures"] == []
    assert comparison["gate_passed"] is False


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
                    "provider_request_budget_failures": 0,
                    "provider_request_min_headroom_tokens": 636681,
                    "provider_stable_prefix_chars": 12345,
                    "provider_stable_prefix_ratio_mean": 0.8125,
                    "context_bounded_observations": 1,
                    "context_bounded_observation_chars_removed": 2784946,
                    "context_duplicate_turns_represented": 2,
                    "context_old_tool_results_cleared": 12,
                    "task_progress_changes": 3,
                    "repository_mirror_transfer_ms": 12.5,
                    "repository_index_refresh_ms": 4.25,
                    "repository_incremental_refreshes": 2,
                },
                "model_call_contexts": [
                    {
                        "stock_context_chars": 100,
                        "runtime_advisory_chars": 0,
                        "context_chars": 100,
                        "context_compiler": {"active_state_chars": 20},
                    },
                    {
                        "stock_context_chars": 150,
                        "runtime_advisory_chars": 80,
                        "context_frontier_chars": 25,
                        "context_chars": 230,
                        "context_compiler": {"active_state_chars": 30},
                    },
                ],
            }
        )
    )

    metrics = extract_trajectory(trajectory, task="task", receipt_path=receipt)

    assert metrics["runtime_advisory_context_chars"] == 80
    assert metrics["context_state_frame_chars_added"] == 50
    assert metrics["context_frontier_chars_added"] == 25
    assert metrics["total_gt_context_chars_added"] == 155
    assert metrics["stock_context_chars_from_receipt"] == 250
    assert metrics["max_context_chars_from_receipt"] == 230
    assert metrics["context_compiler_calls"] == 2
    assert metrics["context_fact_candidates"] == 7
    assert metrics["context_facts_accounted"] == 7
    assert metrics["context_unique_reasoning_chars_removed"] == 0
    assert metrics["context_compiler_effects_considered"] == 5
    assert metrics["context_compiler_effects_unaccounted"] == 0
    assert metrics["preflight_known_segment_operations"] == 3
    assert metrics["provider_request_budget_failures"] == 0
    assert metrics["provider_request_min_headroom_tokens"] == 636681
    assert metrics["provider_stable_prefix_chars"] == 12345
    assert metrics["provider_stable_prefix_ratio_mean"] == 0.8125
    assert metrics["context_bounded_observations"] == 1
    assert metrics["context_bounded_observation_chars_removed"] == 2784946
    assert metrics["context_duplicate_turns_represented"] == 2
    assert metrics["context_old_tool_results_cleared"] == 12
    assert metrics["task_progress_changes"] == 3
    assert metrics["repository_mirror_transfer_ms"] == 12.5
    assert metrics["repository_index_refresh_ms"] == 4.25
    assert metrics["repository_incremental_refreshes"] == 2


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
                    "required_check_claims_without_declared_id": 0,
                    "redundant_provider_payloads": 0,
                    "feature_applicability": {
                        "syntax_result": {
                            "evaluations": 1,
                            "eligible": 1,
                            "fired": 1,
                            "status": "fired_when_eligible",
                            "reason_codes": ["changed_file_syntax_failure"],
                        },
                        "caller_contract": {
                            "evaluations": 1,
                            "eligible": 0,
                            "fired": 0,
                            "status": "correct_abstention",
                            "reason_codes": ["no_certified_direct_callers"],
                        },
                        "recovery": {
                            "evaluations": 0,
                            "eligible": 0,
                            "fired": 0,
                            "status": "trigger_absent",
                            "reason_codes": ["no_lifecycle_evidence_observed"],
                        },
                    },
                    "feature_opportunities": [
                        {
                            "feature_id": "syntax_result",
                            "evidence_status": "eligible",
                            "effect_id": "effect-1",
                        },
                        {
                            "feature_id": "caller_contract",
                            "evidence_status": "correct_abstention",
                            "effect_id": None,
                        },
                    ],
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
                "guidance_deliveries": [{"feature_id": "syntax_result", "evidence_action": 1}],
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
    assert metrics["features_fired"] == 1
    assert metrics["feature_ids_fired"] == ["syntax_result"]
    assert metrics["features_correctly_abstained"] == 1
    assert metrics["feature_ids_correctly_abstained"] == ["caller_contract"]
    assert metrics["features_trigger_absent"] == 1
    assert metrics["feature_ids_trigger_absent"] == ["recovery"]
    assert metrics["feature_missed_triggers"] == 0
    assert metrics["false_feature_fires"] == 0
    assert metrics["required_check_claims_without_declared_id"] == 0
    assert metrics["redundant_provider_payloads"] == 0
    assert "guidance_l1_delivered" not in metrics
    assert "guidance_l3_acted" not in metrics
