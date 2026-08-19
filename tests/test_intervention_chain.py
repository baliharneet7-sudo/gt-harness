from gt_engine.intervention_chain import build_intervention_chain


def test_intervention_chain_joins_delivery_request_and_visible_next_action():
    receipt = {
        "model_call_contexts": [
            {
                "call": 2,
                "request_payload_sha256": "request-2",
                "provider_messages_sha256": "messages-2",
                "changed_message_indices": [3],
                "dispatch_status": "response_received",
            }
        ],
        "repository_context": {
            "deliveries": [
                {
                    "delivery_id": "repo-1",
                    "call": 2,
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
            {"role": "assistant", "content": "done", "reasoning_content": "observed", "extra": {"actions": [{"command": "git diff"}]}},
        ]
    }

    chain = build_intervention_chain(receipt, trajectory)

    assert chain["schema"] == "gt.intervention_chain.v1"
    assert chain["hidden_reasoning_inferred"] is False
    assert chain["counts"] == {
        "rows": 1,
        "visible_model_observations": 1,
        "unknown_causal_status": 1,
    }
    row = chain["rows"][0]
    assert row["provider"]["request_payload_sha256"] == "request-2"
    assert row["model_observation"]["next_actions"] == [{"command": "git diff"}]
    assert row["causal_status"] == "UNKNOWN"
