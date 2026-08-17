from gt_engine.runtime_gate import audit_runtime_receipt


def _receipt() -> dict:
    return {
        "metrics": {
            "effects_produced": 2,
            "effects_applied": 2,
            "effect_trace_rows": 2,
            "context_compiler_effects_unaccounted": 0,
            "inert_private_state_effects": 0,
            "pending_decision_claim_effects": 0,
            "provider_requests_prepared": 1,
            "provider_request_hash_coverage": 1.0,
            "late_payload_deliveries": 0,
            "predictive_payload_deliveries": 0,
            "preemptive_retrieval_selected_evidence": 1,
            "preemptive_retrieval_claims_delivered": 1,
            "preemptive_retrieval_deliveries": 1,
        },
        "contribution_compiler": {
            "calls": [{"candidate_count": 1, "accounted_count": 1}]
        },
        "preemptive_retrieval": {
            "decisions": [
                {"status": "delivered", "delivery_receipt": {"status": "delivered"}}
            ],
            "deliveries": [{"claim_ids": ["claim-1"]}],
        },
    }


def test_runtime_gate_accepts_accounted_delivery():
    failures, summary = audit_runtime_receipt(_receipt(), task="demo")
    assert failures == []
    assert summary["delivered_claims"] == 1


def test_runtime_gate_rejects_selected_retrieval_that_goes_silent():
    receipt = _receipt()
    receipt["metrics"]["preemptive_retrieval_claims_delivered"] = 0
    receipt["metrics"]["preemptive_retrieval_deliveries"] = 0
    receipt["preemptive_retrieval"]["decisions"] = [{"status": "selected"}]
    receipt["preemptive_retrieval"]["deliveries"] = []
    failures, _ = audit_runtime_receipt(receipt, task="demo")
    assert "demo:preemptive_selected_not_delivered" in failures
    assert "demo:preemptive_selected_evidence_silent" in failures


def test_runtime_gate_rejects_unaccounted_private_effect():
    receipt = _receipt()
    receipt["metrics"]["inert_private_state_effects"] = 1
    failures, _ = audit_runtime_receipt(receipt, task="demo")
    assert "demo:inert_private_state_effect" in failures


def test_runtime_gate_rejects_controller_label_without_state_read_evidence():
    receipt = _receipt()
    receipt["metrics"]["pending_decision_claim_effects"] = 1
    receipt["features"] = {
        "effects": [{"receipt_id": "receipt-1"}],
        "effect_applications": [{"receipt_id": "receipt-1"}],
        "effect_trace": [{"effect_id": "receipt-1"}],
        "effect_accountability": [
            {
                "effect_id": "receipt-1",
                "feature_id": "submit_refusal",
                "outcome": "pending_decision_claim",
            }
        ],
        "context_compiler_effect_accountability": [
            {
                "effect_id": "receipt-1",
                "feature_id": "submit_refusal",
                "status": "controller_state_considered",
            }
        ],
    }

    failures, _ = audit_runtime_receipt(receipt, task="demo")

    assert "demo:pending_decision_claim" in failures
    assert "demo:effect_accountability_evidence_missing:receipt-1" in failures


def test_runtime_gate_rejects_no_future_call_label_without_terminal_evidence():
    receipt = _receipt()
    receipt["metrics"]["pending_decision_claim_effects"] = 1
    receipt["features"] = {
        "effect_accountability": [
            {
                "effect_id": "receipt-1",
                "feature_id": "submit_refusal",
                "outcome": "pending_decision_claim",
            }
        ],
        "context_compiler_effect_accountability": [
            {
                "effect_id": "receipt-1",
                "feature_id": "submit_refusal",
                "status": "no_eligible_model_call",
            }
        ],
    }

    failures, _ = audit_runtime_receipt(receipt, task="demo")

    assert "demo:pending_decision_claim" in failures
    assert "demo:effect_accountability_evidence_missing:receipt-1" in failures


def test_runtime_gate_rejects_empty_effect_ledger_when_metric_says_pending():
    receipt = _receipt()
    receipt["metrics"]["pending_decision_claim_effects"] = 1
    receipt["features"] = {
        "effect_accountability": [],
        "context_compiler_effect_accountability": [],
    }

    failures, _ = audit_runtime_receipt(receipt, task="demo")

    assert "demo:effect_accountability_count_mismatch" in failures
    assert "demo:pending_decision_claim" in failures


def test_runtime_gate_rejects_provider_payload_without_delivery_foreign_key():
    receipt = _receipt()
    receipt["metrics"]["pending_decision_claim_effects"] = 1
    receipt["features"] = {
        "effect_accountability": [
            {
                "effect_id": "receipt-1",
                "feature_id": "submit_refusal",
                "outcome": "pending_decision_claim",
                "provider_delivery_ids": [],
            }
        ],
        "context_compiler_effect_accountability": [
            {
                "effect_id": "receipt-1",
                "feature_id": "submit_refusal",
                "status": "provider_payload",
            }
        ],
    }

    failures, _ = audit_runtime_receipt(receipt, task="demo")

    assert "demo:effect_accountability_evidence_missing:receipt-1" in failures
    assert "demo:pending_decision_claim" in failures


def test_runtime_gate_accepts_controller_fact_with_request_evidence():
    receipt = _receipt()
    receipt["metrics"].update(
        effects_produced=1,
        effects_applied=1,
        effect_trace_rows=1,
        pending_decision_claim_effects=1,
    )
    receipt["features"] = {
        "effects": [{"receipt_id": "receipt-1"}],
        "effect_applications": [{"receipt_id": "receipt-1"}],
        "effect_trace": [{"effect_id": "receipt-1"}],
        "effect_accountability": [
            {
                "effect_id": "receipt-1",
                "feature_id": "obligations",
                "outcome": "pending_decision_claim",
            }
        ],
        "context_compiler_effect_accountability": [
            {
                "effect_id": "receipt-1",
                "feature_id": "obligations",
                "status": "controller_state_considered",
                "request_payload_sha256": "a" * 64,
                "fact_id": "fact-1",
                "first_considered_call": 2,
            }
        ],
    }

    failures, _ = audit_runtime_receipt(receipt, task="demo")

    assert failures == []


def test_runtime_gate_accepts_terminal_claim_with_typed_no_future_call_proof():
    receipt = _receipt()
    receipt["metrics"].update(
        effects_produced=1,
        effects_applied=1,
        effect_trace_rows=1,
        pending_decision_claim_effects=1,
    )
    receipt["features"] = {
        "effects": [{"receipt_id": "receipt-1"}],
        "effect_applications": [{"receipt_id": "receipt-1"}],
        "effect_trace": [{"effect_id": "receipt-1"}],
        "effect_accountability": [
            {
                "effect_id": "receipt-1",
                "feature_id": "submit_refusal",
                "outcome": "pending_decision_claim",
            }
        ],
        "context_compiler_effect_accountability": [
            {
                "effect_id": "receipt-1",
                "feature_id": "submit_refusal",
                "status": "no_eligible_model_call",
                "terminal": True,
                "eligible_model_calls_after_effect": 0,
            }
        ],
    }

    failures, _ = audit_runtime_receipt(receipt, task="demo")

    assert failures == []


def test_runtime_gate_rejects_duplicate_effect_foreign_keys():
    receipt = _receipt()
    receipt["features"] = {
        "effect_accountability": [
            {"effect_id": "duplicate", "outcome": "audit_only"},
            {"effect_id": "duplicate", "outcome": "audit_only"},
        ],
        "context_compiler_effect_accountability": [
            {"effect_id": "duplicate", "status": "audit_only"},
            {"effect_id": "duplicate", "status": "audit_only"},
        ],
    }

    failures, _ = audit_runtime_receipt(receipt, task="demo")

    assert "demo:effect_id_duplicate" in failures
    assert "demo:compiler_effect_id_duplicate" in failures


def test_runtime_gate_rejects_malformed_effect_rows():
    receipt = _receipt()
    receipt["features"] = {
        "effect_accountability": ["not-a-row"],
        "context_compiler_effect_accountability": [],
    }

    failures, _ = audit_runtime_receipt(receipt, task="demo")

    assert "demo:effect_accountability_rows_malformed" in failures
    assert "demo:effect_accountability_count_mismatch" in failures


def test_runtime_gate_rejects_malformed_compiler_effect_rows():
    receipt = _receipt()
    receipt["metrics"].update(
        effects_produced=0,
        effects_applied=0,
        effect_trace_rows=0,
    )
    receipt["features"] = {
        "effects": [],
        "effect_applications": [],
        "effect_trace": [],
        "effect_accountability": [],
        "context_compiler_effect_accountability": ["not-a-row"],
    }

    failures, _ = audit_runtime_receipt(receipt, task="demo")

    assert "demo:compiler_effect_accountability_rows_malformed" in failures


def test_runtime_gate_rejects_archived_selected_retrieval_even_if_compiler_rejected_it():
    receipt = _receipt()
    receipt["metrics"]["preemptive_retrieval_deliveries"] = 0
    receipt["metrics"]["preemptive_retrieval_selected_evidence"] = 1
    receipt["metrics"]["preemptive_retrieval_claims_delivered"] = 0
    receipt["preemptive_retrieval"] = {
        "decisions": [{"call": 3, "status": "selected"}],
        "deliveries": [],
    }
    receipt["contribution_compiler"] = {
        "calls": [
            {
                "call": 3,
                "candidate_count": 1,
                "accounted_count": 1,
                "accounting": [
                    {
                        "surface": "preemptive_retrieval",
                        "disposition": "expired_window",
                        "reason_codes": ["first_eligible_request_passed"],
                    }
                ],
            }
        ]
    }

    failures, summary = audit_runtime_receipt(receipt, task="demo")

    assert "demo:preemptive_selected_not_delivered" in failures
    assert "demo:preemptive_selected_evidence_silent" in failures
    assert summary["compiler_rejected"] == 1
