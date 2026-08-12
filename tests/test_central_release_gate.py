from __future__ import annotations

from scripts.central_release_gate import audit_release

STATIC = {
    "census_passed": True,
    "readiness": "READY",
    "pre_smoke_approved": True,
    "exact_commit": True,
}


def _treatment() -> dict:
    return {
        "integration_mode": "active",
        "component_configuration": {
            "context_compaction": True,
            "completion_controller": True,
            "progress_control": True,
            "adaptive_validation_timeout": True,
        },
        "repository_intelligence": {
            "status": "passed",
            "required": True,
            "failures": [],
            "graph_gate": {"blocked": False},
        },
        "preemptive_retrieval": {
            "dense_backend": {
                "available": True,
                "failed": False,
                "backend_identity": "snowflake_onnx:model@sha256:abc",
            },
            "dense_backend_error": "",
            "decisions": [],
            "deliveries": [],
        },
        "decision_sufficiency": {
            "enabled": True,
            "decisions": [],
        },
        "metrics": {
            "repository_intelligence_valid": 1,
            "effects_produced": 0,
            "effects_applied": 0,
            "effect_trace_rows": 0,
            "context_compiler_effects_unaccounted": 0,
            "inert_private_state_effects": 0,
            "pending_decision_claim_effects": 0,
            "provider_requests_prepared": 1,
            "provider_request_hash_coverage": 1.0,
            "late_payload_deliveries": 0,
            "predictive_payload_deliveries": 0,
            "preflight_calls": 0,
            "preflight_duplicate_evidence": 0,
            "provider_view_changed_calls": 0,
        },
        "features": {"effect_trace": [], "preflight_receipts": []},
        "contribution_compiler": {"calls": []},
        "model_call_contexts": [
            {
                "call": 1,
                "request_payload_sha256": "request-1",
                "provider_messages_sha256": "provider-1",
                "stock_provider_messages_sha256": "provider-1",
                "provider_view_changed": False,
                "context_fact_candidates": 0,
                "context_facts_accounted": 0,
            }
        ],
    }


def _off() -> dict:
    receipt = _treatment()
    receipt["integration_mode"] = "off"
    receipt["preemptive_retrieval"] = {"dense_backend": None, "deliveries": []}
    receipt["repository_intelligence"] = {
        "status": "not_applicable",
        "applicability": "not_applicable_no_supported_source",
        "denominator_excluded": True,
        "failures": [],
    }
    receipt["metrics"]["repository_intelligence_valid"] = 0
    return receipt


def test_release_gate_accepts_complete_evidence_contract():
    report = audit_release([_treatment()], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is True
    assert report.status == "READY"
    assert report.schema == "gt.release_gate.v1"
    assert report.summary["checks_passed"] == report.summary["checks_total"]


def test_release_gate_accepts_content_hashed_runtime_dense_identity():
    receipt = _treatment()
    receipt["preemptive_retrieval"]["dense_backend"] = {
        "available": True,
        "backend": "snowflake_onnx",
        "model_name": "Snowflake/snowflake-arctic-embed-m",
        "model_sha256": "a" * 64,
        "network_calls": 0,
        "provider_calls": 0,
    }

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is True


def test_release_gate_fails_closed_when_dense_asset_is_missing():
    receipt = _treatment()
    receipt["preemptive_retrieval"]["dense_backend"] = None

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:dense_backend_receipt_missing" in report.failures


def test_release_gate_fails_closed_when_outcome_preservation_is_disabled():
    receipt = _treatment()
    receipt["component_configuration"]["context_compaction"] = False
    receipt["component_configuration"]["completion_controller"] = False

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:context_compaction_disabled" in report.failures
    assert "treatment-1:completion_controller_disabled" in report.failures


def test_source_less_treatment_does_not_require_repository_or_dense_substrate():
    receipt = _treatment()
    receipt["repository_intelligence"] = {
        "status": "not_applicable",
        "applicability": "not_applicable_no_supported_source",
        "denominator_excluded": True,
        "failures": [],
    }
    receipt["metrics"]["repository_intelligence_valid"] = 0
    receipt["preemptive_retrieval"]["dense_backend"] = None

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is True


def test_release_gate_fails_closed_on_selected_pending_retrieval():
    receipt = _treatment()
    receipt["preemptive_retrieval"]["decisions"] = [{"status": "selected"}]
    receipt["metrics"]["preemptive_retrieval_selected_evidence"] = 1

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:preemptive_selected_not_delivered" in report.failures


def test_release_gate_rejects_retrieval_work_after_task_budget_closed():
    receipt = _treatment()
    receipt["preemptive_retrieval"]["decisions"] = [
        {
            "status": "abstained",
            "opportunity_kind": "post_read_search",
            "ranked_files": [{"path": "src/a.py"}],
            "selected_evidence": [{"path": "src/a.py"}],
            "reason_codes": ["task_character_budget"],
            "channel_receipts": [{"channel": "dense", "latency_ms": 1200}],
        }
    ]

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:retrieval_work_after_budget_closed:1" in report.failures


def test_release_gate_fails_closed_on_uncertified_decision_return():
    receipt = _treatment()
    receipt["metrics"]["preflight_calls"] = 1
    receipt["features"]["preflight_receipts"] = [
        {
            "decision": {"disposition": "return_to_model"},
            "applied_disposition": "pass",
        }
    ]
    receipt["decision_sufficiency"]["decisions"] = [
        {
            "disposition": "return_eligible",
            "return_eligible": True,
            "selecting_request_hash": "request-1",
            "bundle": None,
            "applied_disposition": "pass",
        }
    ]

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:decision_bundle_missing:1" in report.failures


def test_release_gate_rejects_generic_import_as_decision_sufficiency():
    receipt = _treatment()
    receipt["metrics"]["preflight_calls"] = 1
    receipt["features"]["preflight_receipts"] = [
        {"decision": {"disposition": "pass"}, "applied_disposition": "pass"}
    ]
    receipt["decision_sufficiency"]["decisions"] = [
        {
            "disposition": "return_eligible",
            "return_eligible": True,
            "selecting_request_hash": "request-1",
            "retrieval": {"provider_visible_claim_ids": []},
            "bundle": {
                "complete": True,
                "source_revision": "source-1",
                "graph_revision": "graph-1",
                "selecting_request_hash": "request-1",
                "claims": [
                    {
                        "claim_id": "claim-1",
                        "support_kind": "certified_structural",
                        "relation": "inverse:IMPORTS",
                        "provenance": [
                            "structural_certified",
                            "action_target:src/errors.ts",
                            "edge_endpoint_start:80",
                        ],
                    }
                ],
            },
        }
    ]

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:decision_relation_not_material:1" in report.failures


def test_release_gate_fails_closed_on_bad_delivery_hash_and_timing():
    receipt = _treatment()
    receipt["preemptive_retrieval"]["deliveries"] = [
        {
            "frame_id": "frame-1",
            "claim_ids": ["claim-1"],
            "evidence_action": 0,
            "first_eligible_call": 1,
            "delivered_before_call": 1,
            "delivered_before_model_query": True,
            "one_step_late": True,
            "predictive": True,
            "request_payload_sha256": "wrong-request",
            "provider_messages_sha256": "provider-1",
            "chars": 10,
        }
    ]

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert any("delivery_request_hash_context_mismatch" in item for item in report.failures)
    assert any("delivery_timing_invalid" in item for item in report.failures)


def test_release_gate_fails_closed_when_off_arm_changes_provider_view():
    off = _off()
    off["model_call_contexts"][0]["provider_view_changed"] = True

    report = audit_release([_treatment()], static_evidence=STATIC, off_receipts=[off])

    assert report.passed is False
    assert "off-1:provider_view_changed" in report.failures


def test_release_gate_fails_closed_when_static_evidence_is_missing():
    report = audit_release([_treatment()], static_evidence=None, off_receipts=[_off()])

    assert report.passed is False
    assert "missing_static_evidence" in report.failures


def test_release_gate_report_is_json_serializable_and_machine_readable():
    report = audit_release([_treatment()], static_evidence=STATIC, off_receipts=[_off()])
    payload = report.as_dict()

    assert payload["schema"] == "gt.release_gate.v1"
    assert payload["status"] == "READY"
    assert isinstance(payload["checks"], list)
    assert isinstance(payload["failures"], list)


def test_static_gate_accepts_machine_readable_outputs_from_existing_gates():
    static = {
        "census": {"status": "passed"},
        "central_readiness": {"status": "READY"},
        "pre_smoke_approved": {"status": "SMOKE_APPROVED"},
    }
    report = audit_release([_treatment()], static_evidence=static, off_receipts=[_off()])

    assert report.passed is True
