from __future__ import annotations

import hashlib
import json

from gt_engine.central_runtime import CENTRAL_FEATURE_IDS
from scripts.central_release_gate import (
    _contribution_budget,
    _replay_and_intervention_audit,
    audit_release,
    audit_treatment_runtime,
)

STATIC = {
    "census_passed": True,
    "readiness": "READY",
    "pre_smoke_approved": True,
    "exact_commit": True,
}


def _treatment() -> dict:
    return {
        "integration_mode": "active",
        "preflight_mode": "assistive_safe",
        "component_configuration": {
            "context_compaction": True,
            "completion_controller": True,
            "progress_control": True,
            "adaptive_validation_timeout": True,
            "preemptive_retrieval": True,
            "persistent_execution_state": True,
            "task_semantic_substrate": True,
            "convergence_controller": True,
            "gt_request_token_budget": 1200,
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
            "persistent_state_initial_retrieval_calls": 1,
            "persistent_state_bootstrap_calls": 1,
            "bootstrap_api_calls": 1,
        },
        "calls": 2,
        "executor_calls": 1,
        "bootstrap_calls": 1,
        "actions": 0,
        "action_accounting": {
            "schema": "gt.action_accounting.v1",
            "selected": 0,
            "processed": 0,
            "executed": 0,
            "returned": 0,
            "cancelled": 0,
            "selected_equals_processed_plus_cancelled": True,
            "processed_equals_executed_plus_returned": True,
        },
        "host_execution": {"decision_actions": 0},
        "persistent_execution_state": {
            "activation": {
                "initial_applicability": "source_backed",
                "current_applicability": "source_backed",
                "ever_applicable": True,
                "activation_action": 0,
                "activation_call": 0,
                "correctly_abstained": False,
            },
            "initialization": {
                "status": "initialized",
                "catalog": {
                    "graph_source_revision": "source-1",
                    "items": [
                        {
                            "item_id": "pes-1",
                            "retrieval_rank": 1,
                            "provenance": ["hybrid_ranked_candidate"],
                        }
                    ],
                },
            },
            "initial_retrieval": {
                "status": "selected",
                "calls": 1,
                "provider_calls": 0,
                "action_executions": 0,
                "source_revision": "source-1",
                "query_hash": "retrieval-query-1",
                "runtime_cache_seeded": True,
                "runtime_cache_key": "retrieval-cache-1",
                "ranked_files": [{"path": "src/service.py"}],
                "selected_evidence": [{"path": "src/service.py"}],
                "channel_receipts": [
                    {
                        "channel": channel,
                        "candidate_count": 1,
                        "failed": False,
                        "available": True,
                    }
                    for channel in ("exact", "lexical", "bm25", "dense", "structural")
                ],
            },
            "bootstrap": {
                "status": "selected",
                "bootstrap_mode": "generative_selected",
                "logical_calls": 1,
                "provider_calls": 1,
                "action_executions": 0,
                "response_received": True,
                "transport": "direct_single_provider_call",
                "request_payload_sha256": "bootstrap-request",
                "provider_messages_sha256": "bootstrap-provider",
                "visible_catalog_count": 2,
                "visible_catalog_ids_sha256": "catalog-hash",
            },
            "state": {
                "version": 2,
                "graph_current": True,
                "bootstrap_status": "selected",
                "bootstrap_mode": "generative_selected",
                "field_authority": {
                    "primary_focus_id": "bootstrap_selected",
                    "phase": "deterministic_mutable",
                    "current_focus": "executor_observed",
                },
            },
            "metrics": {
                "context_compilations": 1,
                "preflight_projections": 0,
                "postflight_commits": 0,
            },
            "deliveries": [
                {
                    "delivery_id": "state-1",
                    "claim_ids": ["state-claim-1"],
                    "evidence_action": 0,
                    "first_eligible_call": 1,
                    "delivered_before_call": 1,
                    "delivered_before_model_query": True,
                    "not_predictive": True,
                    "one_step_late": False,
                    "request_payload_sha256": "request-1",
                    "provider_messages_sha256": "provider-1",
                    "message_index": 1,
                    "chars": 30,
                    "claim_metadata": [
                        {
                            "claim_id": "state-claim-1",
                            "origin": "preexisting_repository",
                            "authority": "identity_only",
                            "novel_to_provider_view": True,
                            "known_to_model": False,
                            "materiality_reason": "new_unresolved_task_obligation",
                            "source_revision": "source-1",
                            "origin_revision": "source-1",
                            "relation_endpoint": "",
                            "declared_validation_id": "",
                        }
                    ],
                }
            ],
            "failures": [],
            "valid": True,
        },
        "task_semantic_substrate": {
            "schema": "gt.task_semantic_substrate.v1",
            "status": "abstained",
            "derivation": {"status": "abstained", "facts": []},
            "compilations": [
                {
                    "call": 1,
                    "candidate_count": 0,
                    "accounted_count": 0,
                    "selected_count": 0,
                    "accounting": [],
                }
            ],
            "deliveries": [],
        },
        "convergence_controller": {
            "schema": "gt.convergence_controller.v1",
            "preflights": [],
            "return_candidates": 0,
            "applied_returns": 0,
        },
        "product_mechanism_census": {
            "accounting_contract": "17_legacy_features_plus_1_persistent_state",
            "legacy_feature_count": 17,
            "product_mechanism_count": 18,
            "mechanism_ids": [
                *CENTRAL_FEATURE_IDS,
                "persistent_execution_state",
            ],
            "configured_mechanism_count": 18,
            "configured_mechanism_ids": [
                *CENTRAL_FEATURE_IDS,
                "persistent_execution_state",
            ],
            "naturally_fired_legacy_feature_count": 0,
            "naturally_fired_legacy_feature_ids": [],
            "persistent_execution_state": {
                "configured": True,
                "exercised": True,
                "repeated_deterministic_use": True,
                "lifecycle_use_count": 4,
            },
        },
        "features": {"effect_trace": [], "preflight_receipts": []},
        "contribution_compiler": {
            "calls": [
                {
                    "call": 1,
                    "candidate_count": 1,
                    "accounted_count": 1,
                    "payload_tokens": 20,
                    "token_budget": 1200,
                    "selected_surfaces": ["persistent_execution_state"],
                }
            ]
        },
        "model_call_contexts": [
            {
                "call": 1,
                "request_payload_sha256": "request-1",
                "provider_messages_sha256": "provider-1",
                "stock_provider_messages_sha256": "stock-1",
                "provider_view_changed": True,
                "provider_message_count": 2,
                "provider_changed_message_indices": [1],
                "context_fact_candidates": 0,
                "context_facts_accounted": 0,
                "dispatch_status": "response_received",
                "persistent_execution_state_delivered": True,
                "persistent_execution_state": {
                    "kind": "initial",
                    "provider_call": 1,
                    "state_version": 2,
                    "claim_ids": ["state-claim-1"],
                    "reason_codes": [],
                },
            }
        ],
    }


def _off() -> dict:
    receipt = _treatment()
    receipt["integration_mode"] = "off"
    receipt["component_configuration"]["persistent_execution_state"] = False
    receipt["persistent_execution_state"] = {
        "initialization": {"status": "disabled"},
        "initial_retrieval": {"calls": 0},
        "bootstrap": {"provider_calls": 0},
        "state": None,
        "metrics": {},
        "deliveries": [],
        "failures": [],
        "valid": True,
    }
    receipt["calls"] = 1
    receipt["executor_calls"] = 1
    receipt["bootstrap_calls"] = 0
    receipt["preemptive_retrieval"] = {"dense_backend": None, "deliveries": []}
    receipt["repository_intelligence"] = {
        "status": "not_applicable",
        "applicability": "not_applicable_no_supported_source",
        "denominator_excluded": True,
        "failures": [],
    }
    receipt["metrics"]["repository_intelligence_valid"] = 0
    receipt["metrics"]["persistent_state_bootstrap_calls"] = 0
    receipt["metrics"]["persistent_state_initial_retrieval_calls"] = 0
    receipt["metrics"]["bootstrap_api_calls"] = 0
    receipt["model_call_contexts"][0]["stock_provider_messages_sha256"] = "provider-1"
    receipt["model_call_contexts"][0]["provider_view_changed"] = False
    receipt["model_call_contexts"][0]["provider_changed_message_indices"] = []
    return receipt


def _relational_treatment() -> dict:
    receipt = _treatment()
    receipt["treatment_profile"] = "central_relational_v2"
    receipt["component_configuration"].update(
        {
            "step_limit": 100,
            "treatment_runtime_contract_sha256": "",
            "persistent_execution_state": True,
            "relational_context": True,
            "semantic_evidence": True,
            "dense_fallback_only": True,
            "gt_task_evidence_budget_tokens": 4096,
            "gt_task_critical_reserve_tokens": 512,
        }
    )
    contract = {
        "schema": "gt.treatment_runtime_arguments.v1",
        "treatment_id": "fixture-relational",
        "source_sha": "a" * 40,
        "profile_id": "central_relational_v2",
        "agent_kwargs": {
            "integration_mode": "active",
            "treatment_profile": "central_relational_v2",
            "enable_persistent_execution_state": True,
            "enable_preemptive_retrieval": True,
            "enable_relational_context": True,
            "enable_semantic_evidence": True,
            "dense_fallback_only": True,
            "step_limit": 100,
        },
    }
    contract["contract_sha256"] = hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    receipt["treatment_runtime_contract"] = contract
    receipt["component_configuration"]["effective_runtime_agent_kwargs"] = dict(
        contract["agent_kwargs"]
    )
    receipt["component_configuration"]["treatment_runtime_contract_sha256"] = contract[
        "contract_sha256"
    ]
    receipt["preemptive_retrieval"]["decisions"] = [
        {
            "status": "abstained",
            "opportunity_kind": "post_read_search",
            "reason_codes": ["no_supported_context"],
            "cache_hit": False,
            "channel_receipts": [
                {
                    "channel": "dense",
                    "candidate_count": 0,
                    "failed": False,
                    "available": False,
                    "reason": "sparse_supported_dense_skipped",
                    "latency_ms": 0.0,
                }
            ],
        }
    ]
    receipt["preemptive_retrieval"]["opportunity_accounting"] = {
        "schema": "gt.retrieval_opportunity_accounting.v1",
        "opportunities": 1,
    }
    receipt["metrics"].update(
        {
            "relational_context_opportunities": 1,
            "relational_context_deliveries": 1,
            "semantic_evidence_deliveries": 1,
            "repository_context_deliveries": 1,
        }
    )
    receipt["relational_context"] = {
        "schema": "gt.relational_context_runtime.v1",
        "enabled": True,
        "decisions": [
            {
                "call": 1,
                "status": "delivered",
                "opportunity_kind": "post_read_search",
                "source_revision": "source-1",
                "graph_revision": "graph-1",
                "claim_ids": ["process-1"],
                "reason_codes": ["certified_lower_bound"],
            }
        ],
        "deliveries": [
            {
                "delivery_id": "relational-context-1",
                "call": 1,
                "source_revision": "source-1",
                "graph_revision": "graph-1",
                "claim_ids": ["process-1"],
                "evidence_action": 0,
                "first_eligible_call": 1,
                "delivered_before_call": 1,
                "delivered_before_model_query": True,
                "not_predictive": True,
                "one_step_late": False,
                "request_payload_sha256": "request-1",
                "provider_messages_sha256": "provider-1",
                "message_index": 1,
                "chars": 40,
                "tokens": 12,
                "epistemic_status": "lower_bound",
                "processes": [
                    {
                        "process_id": "process-1",
                        "anchor": "src/a.py",
                        "rendered": "src/a.py --calls--> src/b.py",
                        "truncated": False,
                        "cycle_terminated": False,
                    }
                ],
            }
        ],
        "delivered_claim_ids": ["process-1"],
    }
    receipt["semantic_evidence"] = {
        "schema": "gt.semantic_evidence_runtime.v1",
        "enabled": True,
        "decisions": [
            {
                "call": 1,
                "status": "delivered",
                "source_revision": "source-1",
                "graph_revision": "graph-1",
                "claim_ids": ["semantic-1"],
                "reason_codes": [],
            }
        ],
        "deliveries": [
            {
                "delivery_id": "semantic-evidence-1",
                "call": 1,
                "source_revision": "source-1",
                "graph_revision": "graph-1",
                "claim_ids": ["semantic-1"],
                "evidence_action": 0,
                "first_eligible_call": 1,
                "delivered_before_call": 1,
                "delivered_before_model_query": True,
                "not_predictive": True,
                "one_step_late": False,
                "request_payload_sha256": "request-1",
                "provider_messages_sha256": "provider-1",
                "message_index": 1,
                "chars": 35,
                "tokens": 10,
                "items": [
                    {
                        "kind": "definition",
                        "path": "src/a.py",
                        "line": 1,
                        "claim_id": "semantic-1",
                        "source_revision": "source-1",
                    }
                ],
            }
        ],
        "delivered_claim_ids": ["semantic-1"],
    }
    receipt["repository_context"] = {
        "schema": "gt.repository_context_runtime.v1",
        "enabled": True,
        "decisions": [
            {
                "call": 1,
                "status": "delivered",
                "opportunity_kind": "post_read_search",
                "source_revision": "source-1",
                "graph_revision": "graph-1",
                "claim_ids": ["semantic-1", "process-1"],
                "reason_codes": [],
            }
        ],
        "deliveries": [
            {
                "delivery_id": "repository-context-1",
                "call": 1,
                "source_revision": "source-1",
                "graph_revision": "graph-1",
                "claim_ids": ["semantic-1", "process-1"],
                "evidence_action": 0,
                "first_eligible_call": 1,
                "delivered_before_call": 1,
                "delivered_before_model_query": True,
                "not_predictive": True,
                "one_step_late": False,
                "request_payload_sha256": "request-1",
                "provider_messages_sha256": "provider-1",
                "message_index": 1,
                "chars": 70,
                "tokens": 20,
                "claim_metadata": [
                    {
                        "claim_id": claim_id,
                        "origin": "preexisting_repository",
                        "authority": "certified_structural",
                        "materiality_reason": "decision_relevant_repository_context",
                        "source_revision": "source-1",
                    }
                    for claim_id in ("semantic-1", "process-1")
                ],
                "projection": {
                    "status": "deliver",
                    "source_revision": "source-1",
                    "graph_revision": "graph-1",
                    "claim_ids": ["semantic-1", "process-1"],
                    "semantic_evidence": {
                        "items": [{"claim_id": "semantic-1"}],
                    },
                    "execution_views": [{"view_id": "process-1"}],
                    "impact_facts": [],
                },
            }
        ],
        "delivered_claim_ids": ["semantic-1", "process-1"],
    }
    # The strengthened profile composes semantic and relational evidence into
    # one provider surface. The legacy surfaces remain configured for receipt
    # compatibility but do not independently deliver duplicate claims.
    receipt["relational_context"]["deliveries"] = []
    receipt["relational_context"]["delivered_claim_ids"] = []
    receipt["semantic_evidence"]["deliveries"] = []
    receipt["semantic_evidence"]["delivered_claim_ids"] = []
    receipt["metrics"]["relational_context_deliveries"] = 0
    receipt["metrics"]["semantic_evidence_deliveries"] = 0
    receipt["contribution_compiler"]["calls"][0].update(
        {
            "candidate_count": 2,
            "accounted_count": 2,
            "payload_tokens": 40,
            "selected_surfaces": [
                "persistent_execution_state",
                "repository_context",
            ],
        }
    )
    receipt["contribution_compiler"]["task_budget"] = {
        "token_budget": 4096,
        "critical_reserve_tokens": 512,
        "used_regular_tokens": 40,
        "used_critical_tokens": 0,
        "used_tokens": 40,
        "remaining_regular_tokens": 3544,
        "remaining_total_tokens": 4056,
        "exhausted": False,
    }
    receipt["model_call_contexts"][0].update(
        {
            "relational_context": {
                "status": "deliver",
                "claim_ids": ["process-1"],
                "reason_codes": ["certified_lower_bound"],
            },
            "relational_context_delivered": False,
            "semantic_evidence": {
                "status": "deliver",
                "claim_ids": ["semantic-1"],
                "reason_codes": [],
            },
            "semantic_evidence_delivered": False,
            "repository_context": {
                "status": "deliver",
                "claim_ids": ["semantic-1", "process-1"],
                "reason_codes": [],
            },
            "repository_context_delivered": True,
        }
    )
    return receipt


def test_treatment_gate_rejects_unified_contribution_budget_expansion():
    receipt = _treatment()
    receipt["contribution_compiler"]["calls"][0]["payload_tokens"] = 1201

    report = audit_release([receipt], static_evidence=STATIC)

    assert report.passed is False
    assert "treatment-1:contribution_token_budget_exceeded:1" in report.failures


def test_release_gate_excludes_prepared_not_sent_contribution_from_task_usage():
    receipt = {
        "component_configuration": {
            "gt_request_token_budget": 1200,
            "gt_task_evidence_budget_tokens": 4096,
        },
        "model_call_contexts": [{}, {}],
        "contribution_compiler": {
            "calls": [
                {
                    "token_budget": 1200,
                    "task_budget_tokens": 25,
                    "task_budget_token_limit": 4096,
                    "payload_tokens": 25,
                    "candidate_count": 0,
                    "accounted_count": 0,
                    "dispatch_status": "dispatched",
                },
                {
                    "token_budget": 1200,
                    "task_budget_tokens": 25,
                    "task_budget_token_limit": 4071,
                    "payload_tokens": 25,
                    "candidate_count": 0,
                    "accounted_count": 0,
                    "dispatch_status": "prepared_not_sent",
                },
            ],
            "task_budget": {
                "token_budget": 4096,
                "critical_reserve_tokens": 512,
                "used_regular_tokens": 25,
                "used_critical_tokens": 0,
                "used_tokens": 25,
            },
        },
    }

    check = _contribution_budget(receipt, "task-1")

    assert check.passed is True


def test_treatment_gate_rejects_conflated_selected_and_executed_actions():
    receipt = _relational_treatment()
    receipt["action_accounting"].update(
        {"selected": 2, "processed": 1, "executed": 1, "cancelled": 0}
    )

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:selected_action_accounting_mismatch" in report.failures


def test_treatment_gate_rejects_unobserved_runtime_budget_drift():
    receipt = _relational_treatment()
    receipt["component_configuration"]["effective_runtime_agent_kwargs"][
        "gt_task_evidence_budget_tokens"
    ] = 2048
    receipt["treatment_runtime_contract"]["agent_kwargs"][
        "gt_task_evidence_budget_tokens"
    ] = 4096
    contract = dict(receipt["treatment_runtime_contract"])
    contract.pop("contract_sha256", None)
    receipt["treatment_runtime_contract"]["contract_sha256"] = hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    receipt["component_configuration"]["treatment_runtime_contract_sha256"] = receipt[
        "treatment_runtime_contract"
    ]["contract_sha256"]

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert (
        "treatment-1:treatment_runtime_gt_task_evidence_budget_tokens_mismatch"
        in report.failures
    )


def test_release_gate_accepts_complete_evidence_contract():
    report = audit_release(
        [_relational_treatment()], static_evidence=STATIC, off_receipts=[_off()]
    )

    assert report.passed is True
    assert report.status == "READY"
    assert report.schema == "gt.release_gate.v1"
    assert report.summary["checks_passed"] == report.summary["checks_total"]


def test_release_gate_accepts_relational_profile_as_additive_persistent_capability():
    report = audit_release(
        [_relational_treatment()], static_evidence=STATIC, off_receipts=[_off()]
    )

    assert report.passed is True
    assert not any("persistent_" in failure for failure in report.failures)
    assert not any("dense_backend_receipt_missing" in failure for failure in report.failures)


def test_strengthened_release_rejects_legacy_profile_receipt() -> None:
    report = audit_release([_treatment()], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:required_treatment_profile_mismatch" in report.failures


def test_relational_runtime_gate_rejects_missing_treatment_contract() -> None:
    receipt = _relational_treatment()
    receipt.pop("treatment_runtime_contract")

    failures = [
        failure
        for check in audit_treatment_runtime(receipt, label="task")
        for failure in check.failures
    ]

    assert "task:treatment_runtime_contract_missing" in failures


def test_relational_profile_requires_dense_backend_when_fallback_was_attempted():
    receipt = _relational_treatment()
    receipt["preemptive_retrieval"]["dense_backend"] = None
    receipt["preemptive_retrieval"]["decisions"] = [
        {
            "opportunity_kind": "post_read_search",
            "reason_codes": [],
            "cache_hit": False,
            "channel_receipts": [
                {
                    "channel": "dense",
                    "failed": False,
                    "available": False,
                    "reason": "backend_unavailable",
                }
            ]
        }
    ]

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:dense_backend_receipt_missing" in report.failures


def test_relational_profile_requires_provisioned_dense_backend_even_when_skipped():
    receipt = _relational_treatment()
    receipt["preemptive_retrieval"]["dense_backend"] = None

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:dense_backend_receipt_missing" in report.failures


def test_relational_profile_accepts_fully_accounted_correct_abstention():
    receipt = _relational_treatment()
    receipt["repository_context"]["decisions"][0].update(
        {
            "status": "abstain",
            "claim_ids": [],
            "reason_codes": ["no_certified_repository_context"],
        }
    )
    receipt["repository_context"]["deliveries"] = []
    receipt["repository_context"]["delivered_claim_ids"] = []
    receipt["metrics"]["repository_context_deliveries"] = 0
    receipt["contribution_compiler"]["calls"][0].update(
        {
            "candidate_count": 1,
            "accounted_count": 1,
            "payload_tokens": 20,
            "selected_surfaces": ["persistent_execution_state"],
        }
    )
    receipt["model_call_contexts"][0].update(
        {
            "provider_view_changed": False,
            "stock_provider_messages_sha256": "provider-1",
            "provider_changed_message_indices": [],
            "repository_context": {
                "status": "abstain",
                "claim_ids": [],
                "reason_codes": ["no_certified_repository_context"],
            },
            "repository_context_delivered": False,
        }
    )

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    check = next(
        row
        for row in report.checks
        if row.name == "repository_context_integrated_consequence"
    )
    assert check.passed is True
    assert "repository_context_no_integrated_delivery" not in report.failures
    assert check.details["deliveries"] == 0
    assert check.details["opportunities"] == 1
    assert check.details["correct_abstentions_allowed"] is True


def test_release_gate_rejects_legacy_17_only_product_accounting():
    receipt = _treatment()
    receipt["product_mechanism_census"]["product_mechanism_count"] = 17
    receipt["product_mechanism_census"]["mechanism_ids"] = receipt[
        "product_mechanism_census"
    ]["mechanism_ids"][:-1]

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:product_mechanism_count_not_18" in report.failures
    assert "treatment-1:product_mechanism_identity_invalid" in report.failures


def test_release_gate_rejects_configured_but_unexercised_persistent_state():
    receipt = _treatment()
    receipt["product_mechanism_census"]["persistent_execution_state"][
        "exercised"
    ] = False

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:persistent_product_mechanism_not_exercised" in report.failures


def test_release_gate_rejects_one_time_persistent_state_initialization():
    receipt = _treatment()
    persistent = receipt["product_mechanism_census"]["persistent_execution_state"]
    persistent["repeated_deterministic_use"] = False
    persistent["lifecycle_use_count"] = 1

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:persistent_product_mechanism_not_repeated" in report.failures


def test_release_gate_accepts_content_hashed_runtime_dense_identity():
    receipt = _relational_treatment()
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


def test_release_gate_requires_graph_independent_semantic_context():
    receipt = _treatment()
    receipt["component_configuration"]["task_semantic_substrate"] = False

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:task_semantic_substrate_disabled" in report.failures


def test_release_gate_rejects_repeated_or_diagnostic_free_project_probe():
    receipt = _treatment()
    receipt["project_validation"] = {
        "probes": [
            {"source_revision": "s1", "status": "fail", "diagnostic": ""},
            {"source_revision": "s1", "status": "pass", "diagnostic": ""},
        ]
    }
    receipt["metrics"]["project_validation_probe_attempts"] = 2

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:project_probe_failure_without_diagnostic:1" in report.failures
    assert "treatment-1:project_probe_repeated_revision:s1" in report.failures


def test_source_less_treatment_does_not_require_repository_or_dense_substrate():
    receipt = _relational_treatment()
    receipt["repository_intelligence"] = {
        "status": "not_applicable",
        "applicability": "not_applicable_no_supported_source",
        "denominator_excluded": True,
        "failures": [],
    }
    receipt["metrics"]["repository_intelligence_valid"] = 0
    receipt["preemptive_retrieval"]["dense_backend"] = None
    receipt["persistent_execution_state"] = {
        "activation": {
            "initial_applicability": "not_applicable_no_supported_source",
            "current_applicability": "not_applicable_no_supported_source",
            "ever_applicable": False,
            "activation_action": None,
            "activation_call": None,
            "correctly_abstained": True,
        },
        "initialization": {"status": "not_applicable"},
        "initial_retrieval": {"calls": 0},
        "bootstrap": {"provider_calls": 0},
        "state": None,
        "metrics": {},
        "deliveries": [],
        "failures": [],
        "valid": True,
    }
    receipt["calls"] = 1
    receipt["bootstrap_calls"] = 0
    receipt["metrics"]["persistent_state_bootstrap_calls"] = 0
    receipt["metrics"]["persistent_state_initial_retrieval_calls"] = 0
    receipt["metrics"]["bootstrap_api_calls"] = 0
    receipt["product_mechanism_census"]["persistent_execution_state"] = {
        "configured": True,
        "applicable": False,
        "exercised": False,
        "repeated_deterministic_use": False,
        "lifecycle_use_count": 0,
        "bootstrap_calls": 0,
        "correctly_abstained": True,
    }

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is True


def test_release_gate_rejects_missing_persistent_activation_boundary():
    receipt = _treatment()
    receipt["persistent_execution_state"].pop("activation")

    persistent = next(
        check
        for check in audit_treatment_runtime(receipt, label="task")
        if check.name == "persistent_execution_state"
    )

    assert persistent.passed is False
    assert "task:persistent_activation_missing" in persistent.failures


def test_release_gate_counts_only_post_activation_persistent_lifecycle():
    receipt = _treatment()
    receipt["calls"] = 3
    receipt["executor_calls"] = 2
    receipt["actions"] = 2
    receipt["action_accounting"].update(
        {"selected": 2, "processed": 2, "executed": 2}
    )
    receipt["host_execution"]["decision_actions"] = 2
    receipt["persistent_execution_state"]["activation"] = {
        "initial_applicability": "not_applicable_no_supported_source",
        "current_applicability": "source_backed",
        "ever_applicable": True,
        "activation_action": 1,
        "activation_call": 2,
        "correctly_abstained": False,
    }
    receipt["persistent_execution_state"]["metrics"].update(
        {
            "context_compilations": 1,
            "preflight_projections": 1,
            "postflight_commits": 2,
        }
    )
    receipt["model_call_contexts"][0].update(
        {
            "call": 2,
            "persistent_execution_state": {
                "kind": "initial",
                "provider_call": 2,
                "state_version": 2,
                "claim_ids": ["state-claim-1"],
                "reason_codes": [],
            },
        }
    )
    receipt["persistent_execution_state"]["deliveries"][0].update(
        {
            "first_eligible_call": 2,
            "delivered_before_call": 2,
        }
    )
    persistent = next(
        check
        for check in audit_treatment_runtime(receipt, label="dynamic-task")
        if check.name == "persistent_execution_state"
    )

    assert persistent.passed is True


def test_release_gate_uses_lifecycle_counters_not_action_ordinals_after_activation():
    receipt = _treatment()
    receipt["calls"] = 3
    receipt["executor_calls"] = 2
    receipt["actions"] = 4
    receipt["action_accounting"] = {
        "selected": 5,
        "processed": 4,
        "executed": 3,
        "returned": 1,
        "cancelled": 1,
    }
    receipt["host_execution"]["decision_actions"] = 3
    receipt["persistent_execution_state"]["activation"] = {
        "initial_applicability": "not_applicable_no_supported_source",
        "current_applicability": "source_backed",
        "ever_applicable": True,
        "activation_action": 2,
        "activation_call": 2,
        "processed_actions_before_activation": 2,
        "executed_actions_at_activation": 1,
        "correctly_abstained": False,
    }
    receipt["persistent_execution_state"]["metrics"].update(
        {
            "context_compilations": 1,
            "preflight_projections": 2,
            "postflight_commits": 3,
        }
    )
    receipt["model_call_contexts"][0].update(
        {
            "call": 2,
            "persistent_execution_state": {
                "kind": "initial",
                "provider_call": 2,
                "state_version": 2,
                "claim_ids": ["state-claim-1"],
                "reason_codes": [],
            },
        }
    )
    receipt["persistent_execution_state"]["deliveries"][0].update(
        {"first_eligible_call": 2, "delivered_before_call": 2}
    )

    persistent = next(
        check
        for check in audit_treatment_runtime(receipt, label="dynamic-mixed-actions")
        if check.name == "persistent_execution_state"
    )

    assert persistent.passed is True


def test_release_gate_rejects_bootstrap_only_or_silently_missing_living_state():
    receipt = _treatment()
    receipt["persistent_execution_state"]["metrics"]["context_compilations"] = 0
    receipt["persistent_execution_state"]["deliveries"] = []
    receipt["model_call_contexts"][0]["persistent_execution_state"] = None
    receipt["model_call_contexts"][0]["persistent_execution_state_delivered"] = False

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:persistent_context_compilation_count" in report.failures
    assert "treatment-1:persistent_call_accounting_missing:1" in report.failures


def test_release_gate_rejects_retry_wrapped_bootstrap_transport():
    receipt = _treatment()
    receipt["persistent_execution_state"]["bootstrap"]["transport"] = (
        "model_query_single_call"
    )

    checks = audit_treatment_runtime(receipt, label="task")
    persistent = next(check for check in checks if check.name == "persistent_execution_state")

    assert persistent.passed is False
    assert "task:persistent_bootstrap_transport_not_single_call" in persistent.failures


def test_release_gate_rejects_any_provider_query_marker_failure():
    receipt = _treatment()
    receipt["persistent_execution_state"]["bootstrap"]["provider_query_marker_error"] = "OSError"
    receipt["metrics"]["provider_query_marker_error"] = "OSError"

    checks = audit_treatment_runtime(receipt, label="task")
    persistent = next(check for check in checks if check.name == "persistent_execution_state")

    assert persistent.passed is False
    assert "task:persistent_bootstrap_marker_failed" in persistent.failures
    assert "task:executor_provider_marker_failed" in persistent.failures


def test_release_gate_accepts_materiality_accounted_persistent_abstention():
    receipt = _relational_treatment()
    receipt["executor_calls"] = 2
    receipt["calls"] = 3
    receipt["persistent_execution_state"]["metrics"]["context_compilations"] = 2
    receipt["model_call_contexts"].append(
        {
            "call": 2,
            "request_payload_sha256": "request-2",
            "provider_messages_sha256": "provider-2",
            "stock_provider_messages_sha256": "provider-2",
            "provider_view_changed": False,
            "provider_message_count": 2,
            "provider_changed_message_indices": [],
            "context_fact_candidates": 0,
            "context_facts_accounted": 0,
            "dispatch_status": "response_received",
            "persistent_execution_state_delivered": False,
            "persistent_execution_state": {
                "kind": "none",
                "provider_call": 2,
                "state_version": 2,
                "claim_ids": [],
                "reason_codes": [
                    "state_change_already_represented_or_not_model_material"
                ],
            },
        }
    )
    receipt["contribution_compiler"]["calls"].append(
        {
            "call": 2,
            "candidate_count": 0,
            "accounted_count": 0,
            "payload_tokens": 0,
            "token_budget": 1200,
            "selected_surfaces": [],
        }
    )
    receipt["task_semantic_substrate"]["compilations"].append(
        {
            "call": 2,
            "candidate_count": 0,
            "accounted_count": 0,
            "selected_count": 0,
            "accounting": [],
        }
    )

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is True


def test_persistent_state_only_profile_gates_isolation_not_disabled_full_controls():
    receipt = _treatment()
    receipt["preflight_mode"] = "shadow"
    for name in (
        "context_compaction",
        "completion_controller",
        "progress_control",
        "adaptive_validation_timeout",
    ):
        receipt["component_configuration"][name] = False

    full = audit_treatment_runtime(receipt, label="task", profile="certified_full")
    diagnostic = audit_treatment_runtime(receipt, label="task", profile="persistent_state_only")

    outcome_check = next(check for check in full if check.name == "outcome_preservation_controls")
    assert outcome_check.passed is False
    assert next(
        check for check in diagnostic if check.name == "diagnostic_profile_isolation"
    ).passed is True


def test_release_gate_rejects_missing_or_unwired_initial_hybrid_retrieval():
    receipt = _treatment()
    receipt["persistent_execution_state"]["initial_retrieval"] = {
        "status": "disabled",
        "calls": 0,
    }
    receipt["metrics"]["persistent_state_initial_retrieval_calls"] = 0

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:persistent_initial_retrieval_call_count" in report.failures
    assert "treatment-1:persistent_initial_retrieval_incomplete" in report.failures
    assert "treatment-1:persistent_initial_retrieval_channels" in report.failures
    assert "treatment-1:persistent_initial_retrieval_metric_mismatch" in report.failures


def test_graph_substrate_is_not_relabelled_invalid_by_bootstrap_failure():
    receipt = _treatment()
    receipt["repository_evidence"] = {
        "substrate_ready": True,
        "index_current": True,
        "intelligence_valid": True,
    }
    receipt["repository_intelligence"]["status"] = "failed"
    receipt["repository_intelligence"]["failures"] = ["persistent_bootstrap_not_selected"]
    receipt["persistent_execution_state"]["bootstrap"]["status"] = "invalid_fallback"
    receipt["persistent_execution_state"]["bootstrap"][
        "bootstrap_mode"
    ] = "deterministic_fallback"
    receipt["persistent_execution_state"]["state"]["bootstrap_status"] = "invalid_fallback"
    receipt["persistent_execution_state"]["state"][
        "bootstrap_mode"
    ] = "deterministic_fallback"

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])
    substrate = next(check for check in report.checks if check.name == "repository_substrate")

    assert substrate.passed is True
    assert "treatment-1:persistent_bootstrap_not_generative" in report.failures


def test_release_gate_rejects_fallback_bootstrap_as_invalid_treatment():
    receipt = _treatment()
    receipt["persistent_execution_state"]["bootstrap"]["status"] = "invalid_fallback"
    receipt["persistent_execution_state"]["bootstrap"][
        "bootstrap_mode"
    ] = "deterministic_fallback"
    receipt["persistent_execution_state"]["state"]["bootstrap_status"] = "invalid_fallback"
    receipt["persistent_execution_state"]["state"][
        "bootstrap_mode"
    ] = "deterministic_fallback"

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:persistent_bootstrap_not_generative" in report.failures


def test_release_gate_rejects_hidden_extra_calls_with_generative_bootstrap():
    receipt = _treatment()
    receipt["calls"] = 3

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:persistent_provider_call_accounting_mismatch" in report.failures


def test_release_gate_rejects_generative_bootstrap_with_zero_material_deliveries():
    receipt = _treatment()
    receipt["persistent_execution_state"]["deliveries"] = []
    receipt["model_call_contexts"][0]["persistent_execution_state_delivered"] = False
    receipt["model_call_contexts"][0]["persistent_execution_state"] = {
        "kind": "none",
        "claim_ids": [],
        "provider_call": 1,
        "reason_codes": ["not_a_legal_pes_abstention"],
    }

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert report.passed is False
    assert "treatment-1:persistent_no_material_delivery" in report.failures


def test_release_gate_allows_explicit_no_certified_related_file_abstention():
    receipt = _treatment()
    receipt["persistent_execution_state"]["deliveries"] = []
    receipt["model_call_contexts"][0]["persistent_execution_state_delivered"] = False
    receipt["model_call_contexts"][0]["persistent_execution_state"] = {
        "kind": "none",
        "claim_ids": [],
        "provider_call": 1,
        "reason_codes": ["no_certified_related_file"],
    }

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert "treatment-1:persistent_no_material_delivery" not in report.failures


def test_release_gate_allows_history_contains_evidence_empty_pes():
    receipt = _treatment()
    receipt["persistent_execution_state"]["deliveries"] = []
    receipt["model_call_contexts"][0]["persistent_execution_state_delivered"] = False
    receipt["model_call_contexts"][0]["persistent_execution_state"] = {
        "kind": "none",
        "claim_ids": [],
        "provider_call": 1,
        "reason_codes": ["provider_history_already_contains_evidence"],
    }

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert "treatment-1:persistent_no_material_delivery" not in report.failures
    assert "treatment-1:persistent_nonmaterial_abstention_invalid:1" not in report.failures


def test_release_gate_allows_not_model_material_empty_pes():
    receipt = _treatment()
    receipt["persistent_execution_state"]["deliveries"] = []
    receipt["model_call_contexts"][0]["persistent_execution_state_delivered"] = False
    receipt["model_call_contexts"][0]["persistent_execution_state"] = {
        "kind": "none",
        "claim_ids": [],
        "provider_call": 1,
        "reason_codes": ["no_material_certified_localization"],
    }

    report = audit_release([receipt], static_evidence=STATIC, off_receipts=[_off()])

    assert "treatment-1:persistent_no_material_delivery" not in report.failures

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


def test_replay_and_intervention_audit_requires_final_profile_artifacts():
    receipt = {
        "treatment_profile": "central_relational_v2",
        "component_configuration": {"replay_capture": True},
        "replay_bundle": {"enabled": False, "trajectory_replay_ready": False},
        "model_call_contexts": [],
    }

    check = _replay_and_intervention_audit(receipt, "task")

    assert check.passed is False
    assert "task:replay_capture_disabled" in check.failures
    assert "task:intervention_chain_missing" in check.failures


def test_release_gate_report_is_json_serializable_and_machine_readable():
    report = audit_release(
        [_relational_treatment()], static_evidence=STATIC, off_receipts=[_off()]
    )
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
    report = audit_release(
        [_relational_treatment()], static_evidence=static, off_receipts=[_off()]
    )

    assert report.passed is True
