import json
from pathlib import Path

from scripts.tb2_promotion_gate import assess_tb2_promotion, treatment_from_merged

ROOT = Path(__file__).resolve().parents[1]


def _baseline() -> dict:
    return json.loads(
        (ROOT / "eval/frozen_baselines/tb2_miniswe_20260731.json").read_text(
            encoding="utf-8"
        )
    )


def _treatment(*, lose: bool = False, uncached: int = 80) -> dict:
    baseline = _baseline()
    profile = baseline["manifest"]["profiles"]["repair20-v1"]
    baseline_rows = {row["task"]: row for row in baseline["rows"]}
    lose_task = "extract-elf"
    flip_task = "count-dataset-tokens"
    rows = []
    for task in profile["task_ids"]:
        before = baseline_rows[task]
        outcome = bool(before["solved"])
        if task == lose_task and lose:
            outcome = False
        if task == flip_task:
            outcome = True
        provider_calls = int(before["provider_calls"])
        rows.append(
            {
                "task": task,
                "solved": outcome,
                "reward": 1.0 if outcome else 0.0,
                "censored": False,
                "provider_calls": provider_calls,
                "executor_provider_calls": provider_calls,
                "bootstrap_provider_calls": 0,
                "selection_mode": "deterministic_v1",
                "selection_event_count": 1,
                "selection_provider_calls": 0,
                "persistent_applicable": True,
                "total_tokens": max(0, int(before["total_tokens"]) - 100),
                "input_tokens": max(0, int(before["input_tokens"]) - 80),
                "output_tokens": max(0, int(before["output_tokens"]) - 20),
                "uncached_input_tokens": (
                    uncached
                    if task == lose_task
                    else max(0, int(before["uncached_input_tokens"]) - 1)
                ),
                "normalized_cost_usd": max(
                    0.0, float(before["normalized_cost_usd"]) - 0.000001
                ),
            }
        )
    return {
        "schema": "gt.tb2.treatment.v2",
        "manifest": {
            "model": "deepseek-v4-flash",
            "gt_commit": "c" * 40,
            "system_fingerprints": ["different-serving-fingerprint"],
            "profile_id": "repair20-v1",
            "planned_task_ids": list(profile["task_ids"]),
            "task_set_sha256": profile["task_set_sha256"],
            "observed_identity": {
                "executor_models": ["deepseek-v4-flash"],
                "executor_providers": ["openai"],
                "bootstrap_model": "",
                "bootstrap_provider": "",
                "selection_mode": "deterministic_v1",
                "selection_provider_calls": 0,
                "canary_model": "deepseek-v4-flash",
                "canary_provider": "openai",
                "route": "deepseek:native:api.deepseek.com",
                "api_host": "api.deepseek.com",
                "stable": True,
                "complete": True,
            },
            "runtime_contract": {
                **baseline["manifest"]["model_identity"],
                "agent_class": "eval.gt_central_agent:MiniSweCentralAgent",
                "preflight_mode": "assistive_safe",
            },
        },
        "integrity_failures": [],
        "rows": rows,
    }


def test_promotion_requires_zero_losses_a_flip_and_lower_resources():
    report = assess_tb2_promotion(_baseline(), _treatment())

    assert report.passed is True
    assert report.losses == ()
    assert report.flips == ("count-dataset-tokens",)
    assert report.baseline_solved == 17
    assert report.treatment_solved == 18
    assert report.fingerprint_metadata == ("different-serving-fingerprint",)


def test_promotion_rejects_a_provider_call_for_deterministic_selection():
    treatment = _treatment()
    treatment["rows"][0]["selection_provider_calls"] = 1
    treatment["rows"][0]["provider_calls"] += 1

    report = assess_tb2_promotion(_baseline(), treatment)

    assert report.passed is False
    assert "deterministic_selection_provider_call:cobol-modernization" in report.failures


def test_same_model_fingerprint_change_is_metadata_not_a_gate_failure():
    report = assess_tb2_promotion(_baseline(), _treatment())

    assert not any("fingerprint" in failure for failure in report.failures)


def test_promotion_rejects_a_cherry_picked_treatment_subset():
    treatment = _treatment()
    treatment["rows"] = [
        row for row in treatment["rows"] if row["task"] != "extract-elf"
    ]

    report = assess_tb2_promotion(_baseline(), treatment)

    assert report.passed is False
    assert "treatment_task_set_mismatch" in report.failures


def test_promotion_rejects_unknown_profile_even_when_outcomes_pass():
    baseline = _baseline()
    treatment = _treatment()
    treatment["manifest"]["profile_id"] = "invented-profile"

    report = assess_tb2_promotion(baseline, treatment)

    assert report.passed is False
    assert "comparison_profile_unknown:invented-profile" in report.failures


def test_promotion_rejects_requested_model_when_observed_model_differs():
    treatment = _treatment()
    treatment["manifest"]["observed_identity"] = {
        "executor_models": ["different-model"],
        "executor_providers": ["openai"],
        "bootstrap_model": "different-model",
        "bootstrap_provider": "openai",
        "canary_model": "deepseek-v4-flash",
        "canary_provider": "openai",
        "stable": True,
        "complete": True,
    }

    report = assess_tb2_promotion(_baseline(), treatment)

    assert report.passed is False
    assert "observed_model_identity_mismatch" in report.failures


def test_promotion_rejects_non_acting_shadow_preflight_contract():
    treatment = _treatment()
    treatment["manifest"]["runtime_contract"]["preflight_mode"] = "shadow"

    report = assess_tb2_promotion(_baseline(), treatment)

    assert report.passed is False
    assert "treatment_runtime_contract_mismatch:preflight_mode" in report.failures


def test_promotion_rejects_unpinned_baseline_provenance():
    baseline = _baseline()
    baseline["manifest"]["source_artifact_sha256"] = "f" * 64

    report = assess_tb2_promotion(baseline, _treatment())

    assert report.passed is False
    assert "baseline_provenance_mismatch:source_artifact_sha256" in report.failures


def test_promotion_rejects_a_loss_even_with_a_flip():
    report = assess_tb2_promotion(_baseline(), _treatment(lose=True))

    assert report.passed is False
    assert report.losses == ("extract-elf",)
    assert "baseline_solve_regression:extract-elf" in report.failures


def test_promotion_rejects_uncached_input_regression():
    report = assess_tb2_promotion(_baseline(), _treatment(uncached=250_000))

    assert report.passed is False
    assert "common_solved_resource_regression:uncached_input_tokens" in report.failures


def test_promotion_rejects_integrity_failure_and_unaccounted_bootstrap():
    treatment = _treatment()
    treatment["integrity_failures"] = ["task:pending_decision_claim"]
    treatment["rows"][0]["provider_calls"] = 8

    report = assess_tb2_promotion(_baseline(), treatment)

    assert report.passed is False
    assert "treatment_integrity:task:pending_decision_claim" in report.failures
    assert "provider_call_accounting:cobol-modernization" in report.failures


def test_merged_treatment_marks_missing_ungraded_and_missing_receipts_invalid():
    treatment = treatment_from_merged(
        {
            "expected_tasks": 2,
            "missing_tasks": ["artifact-task-missing"],
            "n_trials": 1,
            "n_graded": 0,
            "trial_results": [
                {
                    "task_name": "ungraded__trial",
                    "verifier_result": {"rewards": {}},
                }
            ],
            "receipt_metrics": [],
            "treatment_manifest": {},
        }
    )

    assert "missing_task:artifact-task-missing" in treatment["integrity_failures"]
    assert "trial_count:1/2" in treatment["integrity_failures"]
    assert "graded_count:0/2" in treatment["integrity_failures"]
    assert "receipt_missing:ungraded" in treatment["integrity_failures"]
    assert "censor_state_missing:ungraded" in treatment["integrity_failures"]
    assert treatment["rows"][0]["censored"] is None


def test_merged_treatment_requires_live_bootstrap_route_certification():
    treatment = treatment_from_merged(
        {
            "expected_tasks": 0,
            "missing_tasks": [],
            "n_trials": 0,
            "n_graded": 0,
            "trial_results": [],
            "receipt_metrics": [],
            "treatment_manifest": {},
            "bootstrap_route_certification": {"valid": False},
        }
    )

    assert "bootstrap_route_certification_invalid" in treatment["integrity_failures"]


def test_merged_treatment_uses_one_canonical_multi_reward_outcome():
    treatment = treatment_from_merged(
        {
            "expected_tasks": 1,
            "missing_tasks": [],
            "n_trials": 1,
            "n_graded": 1,
            "trial_results": [
                {
                    "task_name": "mixed__trial",
                    "verifier_result": {
                        "rewards": {"reward": 1, "secondary": 0}
                    },
                }
            ],
            "receipt_metrics": [{"task": "mixed", "censored": False}],
            "treatment_manifest": {"planned_task_ids": ["mixed"]},
        }
    )

    assert treatment["rows"][0]["solved"] is False
    assert treatment["rows"][0]["reward"] == 0.0
    assert treatment["rows"][0]["raw_rewards"] == {"reward": 1, "secondary": 0}


def test_run_32047133236_is_a_permanent_negative_promotion_witness():
    baseline = json.loads(
        (ROOT / "eval/frozen_baselines/tb2_miniswe_20260731.json").read_text(
            encoding="utf-8"
        )
    )
    treatment = json.loads(
        (ROOT / "tests/fixtures/tb2_run_32047133236_treatment.json").read_text(
            encoding="utf-8"
        )
    )

    report = assess_tb2_promotion(baseline, treatment)

    assert report.passed is False
    assert report.baseline_solved == 17
    assert report.treatment_solved == 14
    assert report.flips == ("count-dataset-tokens", "largest-eigenval")
    assert report.losses == (
        "extract-elf",
        "sanitize-git-repo",
        "torch-tensor-parallelism",
        "video-processing",
        "write-compressor",
    )
    assert report.common_solved_resource_deltas["total_tokens"] == -7_542_747.0
    assert report.common_solved_resource_deltas["provider_calls"] == 0.0
    assert report.common_solved_resource_deltas["uncached_input_tokens"] == 347_863.0
    assert report.common_solved_resource_deltas["normalized_cost_usd"] > 0
