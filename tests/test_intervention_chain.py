import hashlib
import json

from gt_engine.intervention_chain import (
    audit_intervention_artifacts,
    build_intervention_chain,
    write_intervention_chain,
)
from gt_engine.replay_bundle import ReplayBundleWriter


def test_intervention_chain_joins_delivery_request_and_visible_next_action():
    receipt = {
        "model_call_contexts": [
            {
                "call": 2,
                "request_payload_sha256": "request-2",
                "provider_messages_sha256": "messages-2",
                "provider_changed_message_indices": [3],
                "dispatch_status": "response_received",
            }
        ],
        "repository_context": {
            "deliveries": [
                {
                    "delivery_id": "repo-1",
                    "delivered_before_call": 2,
                    "claim_ids": ["claim-a"],
                    "source_revision": "src-2",
                    "evidence_action": 1,
                    "eligible_call": 2,
                }
            ]
        },
    }
    trajectory = {
        "messages": [
            {"role": "assistant", "extra": {"actions": [{"command": "pytest"}]}},
            {
                "role": "assistant",
                "content": "done",
                "reasoning_content": "observed",
                "extra": {"actions": [{"command": "git diff"}]},
            },
        ]
    }

    chain = build_intervention_chain(receipt, trajectory)

    assert chain["schema"] == "gt.intervention_chain.v2"
    assert chain["hidden_reasoning_inferred"] is False
    assert chain["counts"]["rows"] == 1
    assert chain["counts"]["canonical_delivery_rows"] == 1
    assert chain["counts"]["surface_counts"] == {"repository_context": 1}
    assert chain["counts"]["visible_model_observations"] == 1
    assert chain["counts"]["causally_unidentifiable"] == 1
    row = chain["rows"][0]
    assert row["provider"]["request_payload_sha256"] == "request-2"
    assert row["provider"]["changed_message_indices"] == [3]
    assert row["model_observation"]["next_actions"] == [{"command": "git diff"}]
    assert row["causal_status"] == "UNIDENTIFIABLE_WITHOUT_COUNTERFACTUAL"


def test_intervention_chain_covers_every_canonical_delivery_surface_and_call():
    receipt = {
        "model_call_contexts": [
            {
                "call": 2,
                "request_payload_sha256": "request-2",
                "provider_messages_sha256": "messages-2",
                "provider_changed_message_indices": [1],
                "dispatch_status": "response_received",
            }
        ],
        "task_semantic_substrate": {
            "deliveries": [
                {
                    "delivery_id": "semantic-1",
                    "delivered_before_call": 2,
                    "claim_ids": ["src/core.py"],
                }
            ]
        },
        "guidance_deliveries": [
            {
                "delivery_id": "guidance-1",
                "delivered_before_call": 2,
                "claim_ids": ["run-tests"],
            }
        ],
        "progress": {
            "fact_deliveries": [
                {
                    "delivery_id": "progress-1",
                    "delivered_before_call": 2,
                    "claim_ids": ["changed-file"],
                }
            ]
        },
        "features": {
            "action_cycles": [
                {
                    "action_id": "action-2",
                    "proposed": {
                        "model_call": 2,
                        "raw_command": "pytest -q",
                        "operation": "check",
                        "validation_kind": "pytest",
                    },
                    "executed": True,
                    "postflight": {"return_code": 0, "source_revision": "src-2"},
                }
            ]
        },
    }
    replay = {
        "calls": [
            {
                "call": 2,
                "response": {
                    "content": "I will run the tests.",
                    "reasoning_content": (
                        "src/core.py changed; run-tests now and record changed-file."
                    ),
                    "extra": {"actions": [{"command": "pytest -q"}]},
                },
            }
        ]
    }

    chain = build_intervention_chain(receipt, replay_bundle=replay)

    assert len(chain["rows"]) == 3
    assert chain["counts"]["surface_counts"] == {
        "guidance": 1,
        "progress": 1,
        "task_semantic_substrate": 1,
    }
    assert {row["provider"]["call"] for row in chain["rows"]} == {2}
    assert all(row["postflight"]["action_cycles"] for row in chain["rows"])
    assert all(
        row["behavioral_uptake"]["status"] == "VISIBLE_REASONING_REFERENCES_CLAIM"
        for row in chain["rows"]
    )


def test_artifact_audit_verifies_replay_chain_and_receipt_as_one_bundle(tmp_path):
    messages = [{"role": "user", "content": "fix"}]
    envelope = {
        "model": "test",
        "model_kwargs": {},
        "tools": [],
        "messages": messages,
    }
    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    replay_writer = ReplayBundleWriter(tmp_path / "gt_replay", enabled=True)
    replay_writer.record_request(
        call=1,
        provider_messages=messages,
        request_envelope=envelope,
        request_payload_sha256=hashlib.sha256(canonical(envelope)).hexdigest(),
        provider_messages_sha256=hashlib.sha256(canonical(messages)).hexdigest(),
        model_name="test",
        model_kwargs={},
        temperature=1.0,
        active_state={},
        source_revision="s1",
        workspace_revision="w1",
    )
    replay_writer.record_response(
        call=1, response={"role": "assistant", "content": "done"}
    )
    replay_metadata = replay_writer.finalize()
    receipt = {
        "treatment_profile": "central_relational_v2",
        "component_configuration": {"replay_capture": True},
        "model_call_contexts": [
            {
                "call": 1,
                "request_payload_sha256": hashlib.sha256(canonical(envelope)).hexdigest(),
                "provider_messages_sha256": hashlib.sha256(canonical(messages)).hexdigest(),
                "provider_changed_message_indices": [],
            }
        ],
        "replay_bundle": replay_metadata,
    }
    receipt_path = tmp_path / "central_receipt.json"
    trajectory_path = tmp_path / "miniswe_trajectory.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    trajectory_path.write_text(json.dumps({"messages": []}), encoding="utf-8")
    receipt["intervention_chain"] = write_intervention_chain(
        receipt_path,
        trajectory_path=trajectory_path,
        replay_bundle_path=tmp_path / "gt_replay",
    )
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    failures, summary = audit_intervention_artifacts(receipt, artifact_root=tmp_path)

    assert failures == []
    assert summary["verified"] is True

    (tmp_path / "intervention_chain.json").write_text("{}", encoding="utf-8")
    failures, _ = audit_intervention_artifacts(receipt, artifact_root=tmp_path)
    assert "intervention_chain_sha256_mismatch" in failures
