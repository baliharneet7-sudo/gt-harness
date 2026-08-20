import json
from pathlib import Path

from scripts.tb2_promotion_gate import task_set_sha256
from scripts.tb2_regression_forensics import build_regression_forensics

ROOT = Path(__file__).resolve().parents[1]


def test_run_320_forensics_preserves_exact_gain_and_loss_sets():
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

    report = build_regression_forensics(baseline, treatment)

    assert report["passed"] is True
    assert report["positive_flips"] == [
        "count-dataset-tokens",
        "largest-eigenval",
    ]
    assert report["negative_flips"] == [
        "extract-elf",
        "sanitize-git-repo",
        "torch-tensor-parallelism",
        "video-processing",
        "write-compressor",
    ]
    loss = next(row for row in report["rows"] if row["task"] == "extract-elf")
    assert loss["attribution"] == "unknown_missing_trajectory"
    assert "verifier tests" in report["integrity_boundary"]


def test_forensics_rejects_treatment_task_hash_drift():
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
    treatment["manifest"]["task_set_sha256"] = "0" * 64

    report = build_regression_forensics(baseline, treatment)

    assert report["passed"] is False
    assert "treatment_task_set_hash_mismatch" in report["failures"]


def test_forensics_joins_first_divergence_delivery_and_model_reasoning(tmp_path):
    task = "demo-task"
    baseline = {
        "rows": [{"task": task, "solved": True}],
        "manifest": {"task_set_sha256": task_set_sha256([task])},
    }
    treatment = {
        "rows": [{"task": task, "solved": False}],
        "manifest": {
            "profile_id": "central_relational_v2",
            "task_set_sha256": task_set_sha256([task]),
        },
    }
    baseline_root = tmp_path / "baseline" / task
    treatment_root = tmp_path / "treatment" / task
    baseline_root.mkdir(parents=True)
    treatment_root.mkdir(parents=True)
    baseline_trajectory = {
        "messages": [
            {
                "role": "assistant",
                "reasoning_content": "Read the local implementation.",
                "extra": {"actions": [{"command": "cat src/local.py"}]},
            }
        ]
    }
    treatment_trajectory = {
        "messages": [
            {
                "role": "assistant",
                "reasoning_content": "Inspect src/caller.py because it calls the target.",
                "extra": {"actions": [{"command": "cat src/caller.py"}]},
            }
        ]
    }
    (baseline_root / "miniswe_trajectory.json").write_text(
        json.dumps(baseline_trajectory), encoding="utf-8"
    )
    (treatment_root / "miniswe_trajectory.json").write_text(
        json.dumps(treatment_trajectory), encoding="utf-8"
    )
    receipt = {
        "model_call_contexts": [
            {
                "call": 1,
                "control_provider_messages_sha256": "control",
                "provider_messages_sha256": "provider",
                "request_payload_sha256": "request",
                "provider_message_count": 2,
                "provider_changed_message_indices": [1],
                "dispatch_status": "response_received",
                "context_fact_candidates": 0,
                "context_facts_accounted": 0,
            }
        ],
        "guidance_deliveries": [
            {
                "delivery_id": "delivery-1",
                "claim_ids": ["caller-claim"],
                "evidence_action": 0,
                "first_eligible_call": 1,
                "delivered_before_call": 1,
                "delivered_before_model_query": True,
                "not_predictive": True,
                "one_step_late": False,
                "request_payload_sha256": "request",
                "provider_messages_sha256": "provider",
                "message_index": 1,
                "chars": 20,
            }
        ],
        "repository_intelligence": {"frontier_deliveries": []},
        "contribution_compiler": {
            "provider_value_contract": "gt.provider_value.v1",
            "calls": [
                {
                    "call": 1,
                    "value_certificates": [
                        {
                            "claim_id": "caller-claim",
                            "value_class": "action_local_relation",
                            "disposition": "same_observation",
                            "completeness": "exact",
                            "authority": "certified_structural",
                            "anchors": ["src/caller.py"],
                            "novelty_basis": "nonlocal_relation_absent_from_observation",
                            "decision_point": "next_executor_request",
                            "replaces_operation": "repository_relationship_search",
                        }
                    ],
                }
            ],
        },
    }
    (treatment_root / "central_receipt.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )

    report = build_regression_forensics(
        baseline,
        treatment,
        baseline_trajectory_root=tmp_path / "baseline",
        treatment_artifact_root=tmp_path / "treatment",
    )

    row = report["rows"][0]
    detail = row["first_divergence_detail"]
    assert detail["baseline_command"] == "cat src/local.py"
    assert detail["treatment_command"] == "cat src/caller.py"
    assert detail["preceding_gt_deliveries"][0]["reasoning_uptake"] is True
    assert detail["reasoning_uptake_is_proxy_not_causal_proof"] is True
