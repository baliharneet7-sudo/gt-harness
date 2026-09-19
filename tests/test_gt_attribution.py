from __future__ import annotations

import functools
import json
import pathlib
import subprocess
import types

import pytest

from gt_engine.attribution import (
    CAPABILITY_OWNERS,
    DIRECT_FEATURES,
    AttributionTrace,
    feature_for_evidence,
    summarize_features,
    verify_lifecycle_rows,
    verify_trace_rows,
)


def test_direct_feature_registry_is_exact_and_complete():
    facts = {name for name, spec in DIRECT_FEATURES.items() if spec["kind"] == "FACT"}
    caps = {name for name, spec in DIRECT_FEATURES.items() if spec["kind"] == "CAP"}

    assert facts == {
        "caller_contract",
        "cochange_prior",
        "covering_red",
        "def_partition",
        "localization",
        "newfile_precedent",
        "obligations",
        "recovery",
        "signature_delta",
        "submit_refusal",
        "syntax_result",
    }
    assert caps == {
        "GT_CERT_DELIVERY",
        "GT_CHANGE_SURFACE",
        "GT_EDIT_CHECK",
        "GT_HYPOTHESIS",
        "GT_LOC_RESLOT",
        "GT_PATCH_DELTA",
        "GT_SS_SUBMIT_RED",
        "persistent_plan",
        "plan_gate",
        "select_catalog",
    }
    assert len(DIRECT_FEATURES) == 21
    assert all(spec["boundaries"] for spec in DIRECT_FEATURES.values())
    assert all(spec["trigger"] for spec in DIRECT_FEATURES.values())
    assert all(spec["intended_action"] for spec in DIRECT_FEATURES.values())
    assert CAPABILITY_OWNERS == {
        "GT_CHANGE_SURFACE": "newfile_precedent",
        "GT_PATCH_DELTA": "signature_delta",
        "GT_LOC_RESLOT": "localization",
        "GT_SS_SUBMIT_RED": "submit_refusal",
        "GT_EDIT_CHECK": "syntax_result",
        "GT_HYPOTHESIS": "recovery",
        "GT_CERT_DELIVERY": "submit_refusal",
    }


def test_cochange_evidence_binds_to_dark_trigger_identity():
    assert feature_for_evidence("cochange_partner") == "cochange_prior"


def test_attribution_trace_is_append_only_hash_chained(tmp_path):
    path = tmp_path / "gt_attribution.jsonl"
    trace = AttributionTrace(lambda: path, trace_id="a" * 32)

    first = trace.record(
        "observation.received",
        action_index=1,
        boundary="gateway",
        payload={"tool_name": "bash", "changed_files": ["src/a.py"]},
    )
    second = trace.record(
        "decision.committed",
        action_index=1,
        boundary="gateway",
        payload={"decision": "no_candidate", "reason": "producer_abstained"},
    )

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows == [first, second]
    assert rows[0]["previous_hash"] == ""
    assert rows[1]["previous_hash"] == rows[0]["row_hash"]
    assert rows[0]["sequence"] == 1
    assert rows[1]["sequence"] == 2
    assert verify_trace_rows(rows) == []


def test_newfile_missing_role_evidence_maps_to_canonical_feature():
    assert feature_for_evidence("missing_role:registration") == (
        "newfile_precedent"
    )
    assert feature_for_evidence("missing_role_postcreate:template") == (
        "newfile_precedent"
    )


def test_groundtruth_registry_aliases_map_to_the_same_17_identities():
    assert feature_for_evidence("name_fold") == "def_partition"
    assert feature_for_evidence("wrong_surface") == "def_partition"
    assert feature_for_evidence("body_concept") == "def_partition"
    assert feature_for_evidence("trace_frame") == "localization"
    assert feature_for_evidence("brief_localization") == "localization"
    assert feature_for_evidence("companion_surface") == "signature_delta"
    assert feature_for_evidence("caller_contract_search") == "caller_contract"
    assert feature_for_evidence("coherence_collapse") == "recovery"
    assert feature_for_evidence("obligation_unexercised") == "obligations"
    assert feature_for_evidence("select_catalog") == "select_catalog"


def test_trace_integrity_rejects_mutated_payload(tmp_path):
    path = tmp_path / "gt_attribution.jsonl"
    trace = AttributionTrace(lambda: path, trace_id="b" * 32)
    trace.record(
        "decision.committed",
        action_index=2,
        boundary="submit",
        payload={"decision": "suppressed", "reason": "over_budget"},
    )
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["payload"]["reason"] = "sealed_and_delivered"

    assert verify_trace_rows(rows) == ["row 1: row_hash mismatch"]


def test_sensitive_payload_values_are_hashed_not_persisted(tmp_path):
    path = tmp_path / "gt_attribution.jsonl"
    trace = AttributionTrace(lambda: path, trace_id="c" * 32)
    secret = "provider-secret-value"
    trace.record_content(
        "model.response",
        content=secret,
        action_index=3,
        boundary="model",
        payload={"delivery_ids": ["d1"]},
    )

    raw = path.read_text(encoding="utf-8")
    row = json.loads(raw)
    assert secret not in raw
    assert row["payload"]["content_chars"] == len(secret)
    assert len(row["payload"]["content_sha256"]) == 64


def test_lifecycle_verifier_allows_provider_after_multi_tool_batch():
    rows = [
        {
            "sequence": 1,
            "action_index": 4,
            "event_type": "decision.committed",
            "payload": {
                "decision": "delivered",
                "delivery_id": "d4",
                "rendered_bytes_hash": "a" * 64,
            },
        },
        {
            "sequence": 2,
            "action_index": 4,
            "event_type": "provider.request",
            "payload": {
                "iteration": 5,
                "delivery_ids": ["d4"],
                "matches": [{
                    "delivery_id": "d4",
                    "rendered_sha256": "a" * 64,
                    "locations": ["1.content"],
                }],
            },
        },
        {
            "sequence": 3,
            "action_index": 4,
            "event_type": "model.response",
            "payload": {"iteration": 5, "delivery_ids": ["d4"]},
        },
    ]

    assert verify_lifecycle_rows(rows) == []

    rows[1]["action_index"] = 7
    rows[2]["action_index"] = 7
    assert verify_lifecycle_rows(rows) == []


def test_lifecycle_verifier_requires_immediate_provider_and_response_link():
    rows = [
        {
            "sequence": 1,
            "action_index": 4,
            "event_type": "decision.committed",
            "payload": {
                "decision": "delivered",
                "delivery_id": "d4",
                "rendered_bytes_hash": "a" * 64,
            },
        },
        {
            "sequence": 2,
            "action_index": 7,
            "event_type": "provider.request",
            "payload": {
                "iteration": 5,
                "delivery_ids": [],
                "matches": [],
            },
        },
        {
            "sequence": 3,
            "action_index": 7,
            "event_type": "model.response",
            "payload": {"iteration": 5, "delivery_ids": []},
        },
        {
            "sequence": 4,
            "action_index": 8,
            "event_type": "provider.request",
            "payload": {
                "iteration": 6,
                "delivery_ids": ["d4"],
                "matches": [{
                    "delivery_id": "d4",
                    "rendered_sha256": "a" * 64,
                    "locations": ["1.content"],
                }],
            },
        },
        {
            "sequence": 5,
            "action_index": 8,
            "event_type": "model.response",
            "payload": {"iteration": 6, "delivery_ids": ["d4"]},
        },
    ]

    assert verify_lifecycle_rows(rows) == [
        "delivery d4: missing from immediate provider-final request",
        "delivery d4: provider byte match missing",
        "delivery d4: missing from immediate model response",
    ]


def test_lifecycle_verifier_rejects_missing_or_hash_mismatched_receipt():
    delivered = {
        "sequence": 1,
        "action_index": 2,
        "event_type": "decision.committed",
        "payload": {
            "decision": "delivered",
            "delivery_id": "d2",
            "rendered_bytes_hash": "b" * 64,
        },
    }
    assert verify_lifecycle_rows([delivered]) == [
        "delivery d2: missing provider-final request receipt",
        "delivery d2: missing linked model response",
    ]

    rows = [
        delivered,
        {
            "sequence": 2,
            "action_index": 2,
            "event_type": "provider.request",
            "payload": {
                "iteration": 3,
                "delivery_ids": ["d2"],
                "matches": [{
                    "delivery_id": "d2",
                    "rendered_sha256": "c" * 64,
                    "locations": ["2.content"],
                }],
            },
        },
        {
            "sequence": 3,
            "action_index": 2,
            "event_type": "model.response",
            "payload": {"iteration": 3, "delivery_ids": ["d2"]},
        },
    ]
    assert verify_lifecycle_rows(rows) == [
        "delivery d2: provider receipt hash does not match sealed bytes"
    ]


def test_feature_summary_distinguishes_delivery_dark_suppressed_and_ineligible():
    rows = [
        {
            "event_type": "decision.committed",
            "payload": {
                "decision": "delivered",
                "reason": "sealed_and_delivered",
                "delivery_id": "1",
                "feature_id": "localization",
                "evidence_type": "localization",
            },
        },
        {
            "event_type": "provider.request",
            "payload": {"iteration": 2, "delivery_ids": ["1"]},
        },
        {
            "event_type": "model.response",
            "payload": {"iteration": 2, "delivery_ids": ["1"], "tool_calls": []},
        },
        {
            "event_type": "feature.evaluated",
            "payload": {
                "feature_id": "recovery",
                "eligible": True,
                "outcome": "producer_abstained",
            },
        },
        {
            "event_type": "producer.invocation",
            "payload": {
                "outcome": "returned_fact",
                "evidence_types": ["signature_mismatch"],
            },
        },
        {
            "event_type": "decision.committed",
            "payload": {
                "decision": "suppressed",
                "reason": "over_budget",
                "evidence_type": "signature_mismatch",
            },
        },
        {
            "event_type": "producer.invocation",
            "payload": {
                "outcome": "returned_nothing",
                "evidence_types": ["def_ref_partition"],
                "abstention_reasons": [
                    {"category": "correct_quiet", "reason": "definition_absent"}
                ],
            },
        },
    ]

    summary = summarize_features(rows)

    assert summary["localization"]["status"] == "WITNESSED"
    assert summary["localization"]["exposed"] is True
    assert summary["localization"]["response_observed"] is True
    assert summary["recovery"]["status"] == "TRIGGERED_DARK"
    assert summary["signature_delta"]["status"] == "SUPPRESSED_WITH_REASON"
    assert summary["signature_delta"]["reasons"] == ["over_budget"]
    assert summary["def_partition"]["status"] == "INELIGIBLE"
    assert summary["covering_red"]["status"] == "INELIGIBLE"


@pytest.mark.gt_all17
def test_capabilities_require_explicit_application_receipts():
    rows = []
    for action_index, (capability, fact_id) in enumerate(
        CAPABILITY_OWNERS.items(), 1
    ):
        delivery_id = f"d{action_index}"
        rows.extend([
            {
                "event_type": "decision.committed",
                "action_index": action_index,
                "payload": {
                    "decision": "delivered",
                    "delivery_id": delivery_id,
                    "feature_id": fact_id,
                    "evidence_type": fact_id,
                },
            },
            {
                "event_type": "capability.applied",
                "action_index": action_index,
                "payload": {
                    "feature_id": capability,
                    "fact_id": fact_id,
                    "delivery_id": delivery_id,
                    "decision": "APPLIED",
                },
            },
            {
                "event_type": "provider.request",
                "action_index": action_index,
                "payload": {"delivery_ids": [delivery_id]},
            },
            {
                "event_type": "model.response",
                "action_index": action_index,
                "payload": {"delivery_ids": [delivery_id]},
            },
        ])

    summary = summarize_features(rows)

    for capability, fact_id in CAPABILITY_OWNERS.items():
        assert summary[fact_id]["status"] == "WITNESSED"
        assert summary[capability]["status"] == "WITNESSED"
        assert summary[capability]["reasons"] == ["capability_applied"]


def test_delivered_fact_does_not_automatically_credit_capability_owner():
    rows = [
        {
            "event_type": "decision.committed",
            "payload": {
                "decision": "delivered",
                "delivery_id": "d1",
                "feature_id": "localization",
                "evidence_type": "localization",
            },
        },
        {
            "event_type": "provider.request",
            "payload": {"delivery_ids": ["d1"]},
        },
        {
            "event_type": "model.response",
            "payload": {"delivery_ids": ["d1"]},
        },
    ]

    summary = summarize_features(rows)

    assert summary["localization"]["status"] == "WITNESSED"
    assert summary["GT_LOC_RESLOT"]["status"] == "INELIGIBLE"


def test_compound_feature_receipt_credits_a_fact_without_second_delivery():
    rows = [
        {
            "event_type": "decision.committed",
            "payload": {
                "decision": "delivered",
                "delivery_id": "0",
                "feature_id": "obligations",
                "evidence_type": "obligations",
            },
        },
        {
            "event_type": "feature.applied",
            "payload": {
                "feature_id": "localization",
                "delivery_id": "0",
                "decision": "APPLIED",
                "reason": "compound_task_start_orientation",
            },
        },
        {
            "event_type": "capability.applied",
            "payload": {
                "feature_id": "GT_LOC_RESLOT",
                "fact_id": "localization",
                "delivery_id": "0",
                "decision": "APPLIED",
            },
        },
        {
            "event_type": "provider.request",
            "payload": {"iteration": 1, "delivery_ids": ["0"]},
        },
        {
            "event_type": "model.response",
            "payload": {"iteration": 1, "delivery_ids": ["0"]},
        },
    ]

    summary = summarize_features(rows)

    assert summary["obligations"]["status"] == "WITNESSED"
    assert summary["localization"]["status"] == "WITNESSED"
    assert summary["GT_LOC_RESLOT"]["status"] == "WITNESSED"
    assert summary["localization"]["deliveries"] == ["0"]


def test_feature_provider_iterations_report_exact_delivery_timing():
    from gt_engine.attribution import feature_provider_iterations

    rows = [
        {
            "event_type": "decision.committed",
            "payload": {
                "decision": "delivered",
                "delivery_id": "0",
                "feature_id": "obligations",
            },
        },
        {
            "event_type": "feature.applied",
            "payload": {
                "decision": "APPLIED",
                "delivery_id": "0",
                "feature_id": "localization",
            },
        },
        {
            "event_type": "capability.applied",
            "payload": {
                "decision": "APPLIED",
                "delivery_id": "0",
                "feature_id": "GT_LOC_RESLOT",
                "fact_id": "localization",
            },
        },
        {
            "event_type": "provider.request",
            "payload": {"iteration": 1, "delivery_ids": ["0"]},
        },
        {
            "event_type": "decision.committed",
            "payload": {
                "decision": "delivered",
                "delivery_id": "7",
                "feature_id": "localization",
            },
        },
        {
            "event_type": "provider.request",
            "payload": {"iteration": 4, "delivery_ids": ["7"]},
        },
    ]

    timing = feature_provider_iterations(rows)

    assert timing["obligations"] == [1]
    assert timing["localization"] == [1, 4]
    assert timing["GT_LOC_RESLOT"] == [1]


def test_sdlc_timing_requires_pre_edit_before_dispatch_and_post_edit_after():
    from gt_engine.attribution import verify_sdlc_timing_rows

    valid = [
        {
            "sequence": 1,
            "action_index": 0,
            "event_type": "lifecycle.checkpoint",
            "boundary": "pre_edit",
            "payload": {
                "phase": "pre_edit",
                "proposed_action_index": 1,
            },
        },
        {
            "sequence": 2,
            "action_index": 1,
            "event_type": "observation.received",
            "payload": {
                "tool_name": "edit_file",
                "changed_files": ["pkg/a.py"],
            },
        },
        {
            "sequence": 3,
            "action_index": 1,
            "event_type": "lifecycle.checkpoint",
            "boundary": "post_edit",
            "payload": {"phase": "post_edit"},
        },
    ]
    invalid = [
        {**valid[1], "sequence": 1},
        {**valid[0], "sequence": 2},
    ]

    assert verify_sdlc_timing_rows(valid) == []
    issues = verify_sdlc_timing_rows(invalid)
    assert any("pre_edit occurs after dispatch" in issue for issue in issues)
    assert any("missing post_edit" in issue for issue in issues)


def test_unterminated_producer_invocation_is_telemetry_fault():
    rows = [{
        "event_type": "producer.invocation",
        "payload": {
            "invocation_id": "inv-1",
            "outcome": "entered",
            "evidence_types": ["def_ref_partition"],
        },
    }]

    summary = summarize_features(rows)

    assert summary["def_partition"]["status"] == "TELEMETRY_FAULT"
    assert summary["def_partition"]["reasons"] == ["producer_terminal_missing"]


def test_cap_is_witnessed_only_when_same_action_delivers_its_fact():
    rows = [
        {
            "action_index": 9,
            "event_type": "capability.applied",
            "payload": {
                "feature_id": "GT_HYPOTHESIS",
                "fact_id": "recovery",
                "delivery_id": "9",
                "decision": "APPLIED",
            },
        },
        {
            "action_index": 9,
            "event_type": "provider.request",
            "payload": {"delivery_ids": ["9"]},
        },
        {
            "action_index": 9,
            "event_type": "model.response",
            "payload": {"delivery_ids": ["9"]},
        },
        {
            "action_index": 10,
            "event_type": "feature.evaluated",
            "payload": {
                "feature_id": "GT_HYPOTHESIS",
                "eligible": True,
                "outcome": "candidate_returned",
            },
        },
        {
            "action_index": 9,
            "event_type": "decision.committed",
            "payload": {
                "decision": "delivered",
                "delivery_id": "9",
                "feature_id": "recovery",
                "evidence_type": "recovery",
            },
        },
        {
            "action_index": 10,
            "event_type": "feature.evaluated",
            "payload": {
                "feature_id": "GT_CERT_DELIVERY",
                "eligible": True,
                "outcome": "candidate_returned",
            },
        },
    ]

    summary = summarize_features(rows)

    assert summary["GT_HYPOTHESIS"]["status"] == "WITNESSED"
    assert summary["GT_CERT_DELIVERY"]["status"] == "TRIGGERED_DARK"


def test_executed_clean_edit_check_is_witnessed_but_no_target_is_ineligible():
    rows = [
        {
            "action_index": 4,
            "event_type": "feature.evaluated",
            "payload": {
                "feature_id": "GT_EDIT_CHECK",
                "eligible": True,
                "outcome": "ok",
            },
        },
        {
            "action_index": 4,
            "event_type": "capability.applied",
            "payload": {
                "feature_id": "GT_EDIT_CHECK",
                "fact_id": "syntax_result",
                "delivery_id": "",
                "decision": "APPLIED",
            },
        },
    ]
    assert summarize_features(rows)["GT_EDIT_CHECK"]["status"] == "WITNESSED"

    quiet_rows = [{
        "action_index": 4,
        "event_type": "feature.evaluated",
        "payload": {
            "feature_id": "GT_EDIT_CHECK",
            "eligible": False,
            "outcome": "no_edited_syntax_target",
        },
    }]
    assert (
        summarize_features(quiet_rows)["GT_EDIT_CHECK"]["status"]
        == "INELIGIBLE"
    )


def test_named_correct_quiet_outcome_is_retained_for_ineligible_feature():
    rows = [{
        "action_index": 0,
        "event_type": "feature.evaluated",
        "payload": {
            "feature_id": "obligations",
            "eligible": False,
            "outcome": "brief_empty",
        },
    }]

    summary = summarize_features(rows)

    assert summary["obligations"]["status"] == "INELIGIBLE"
    assert summary["obligations"]["reasons"] == ["brief_empty"]


def test_authority_abstention_is_named_suppression_not_triggered_dark():
    rows = [{
        "event_type": "producer.invocation",
        "payload": {
            "outcome": "returned_nothing",
            "evidence_types": ["caller_contract_view"],
            "abstention_reasons": [{
                "category": "authority",
                "reason": "viewed_file_leaky",
            }],
        },
    }]

    summary = summarize_features(rows)

    assert summary["caller_contract"]["status"] == "SUPPRESSED_WITH_REASON"
    assert summary["caller_contract"]["reasons"] == ["viewed_file_leaky"]


def test_registry_abstention_is_named_suppression_not_ineligible():
    rows = [{
        "event_type": "producer.invocation",
        "payload": {
            "outcome": "returned_nothing",
            "evidence_types": ["caller_contract_view"],
            "abstention_reasons": [{
                "category": "registry",
                "reason": "producer_disabled",
            }],
        },
    }]

    summary = summarize_features(rows)

    assert summary["caller_contract"]["status"] == "SUPPRESSED_WITH_REASON"
    assert summary["caller_contract"]["reasons"] == ["producer_disabled"]


def test_router_suppression_is_attributed_to_canonical_evidence_feature():
    rows = [{
        "event_type": "control.decision",
        "payload": {
            "feature_id": "GT_ROLE_DRIVEN_COALITION",
            "decision": "SUPPRESSED",
            "reason": "not_grounded_in_content_search",
            "evidence_type": "localization",
        },
    }]

    summary = summarize_features(rows)

    assert summary["localization"]["status"] == "SUPPRESSED_WITH_REASON"
    assert summary["localization"]["reasons"] == [
        "not_grounded_in_content_search"
    ]


def test_carried_delivery_does_not_overwrite_immediate_response_action():
    """Old GT bytes remain in later conversation history. The first linked
    response is the causal boundary; later actions must not overwrite it."""
    rows = [
        {
            "event_type": "decision.committed",
            "payload": {
                "decision": "delivered",
                "delivery_id": "d1",
                "feature_id": "localization",
                "evidence_type": "localization",
            },
        },
        {
            "event_type": "provider.request",
            "payload": {"delivery_ids": ["d1"]},
        },
        {
            "event_type": "model.response",
            "payload": {"delivery_ids": ["d1"]},
        },
        {
            "event_type": "response.action",
            "payload": {
                "delivery_id": "d1",
                "feature_id": "localization",
                "classification": "target_referenced",
            },
        },
        {
            "event_type": "response.action",
            "payload": {
                "delivery_id": "d1",
                "feature_id": "localization",
                "classification": "no_tool_action",
            },
        },
    ]

    summary = summarize_features(rows)

    assert summary["localization"]["action_observed"] is True
    assert summary["localization"]["action_consistent"] is True


def test_transcript_parser_consumes_gt_index_diagnostics_as_structured_noise():
    from scripts.gt_audit import parse_transcript

    transcript = (
        "GroundTruth: gt-index failed: Pass 1: discovering files\n"
        "Found 1 source files,\n"
        "Pass 2: parsing 1 files (4 workers)......\n"
        "stop: max_iterations  iterations=1  in=1 out=1 cache_read=0\n"
    )
    parsed = parse_transcript(transcript)
    assert parsed.unparsed == []
    assert parsed.stop is not None


def test_delivery_budget_refusal_is_named_suppression_not_triggered_dark():
    """A refusal by a designed ceiling is suppression, not a dark fire.

    Real record, SWE-Live run 35252797829, task aiogram__aiogram-1594,
    ``agent/events.jsonl`` sequence 83 (verbatim keys, trimmed hashes)::

        {"action_index": 1, "admitted_bytes": 3324, "admitted_count": 4,
         "boundary_claim_limit": 4, "candidate_ordinal": 5,
         "delivery_identity": "19b053b8...", "event": "delivery_refused",
         "iteration": 3, "kind": "cochange_partner", "lane": "sealed",
         "per_delivery_limit": 1400, "reason": "boundary_claim_ceiling",
         "rendered_bytes": 735, "request_byte_limit": 9600,
         "schema": "gt.event.v1", "sequence": 83,
         "target": "/testbed/aiogram/fsm/context.py"}

    ``scripts.gt_audit._native_feature_projection`` maps that row to a
    ``feature.evaluated`` row with ``eligible`` true (the reason is not one of
    the three it excludes) and ``outcome`` set to the refusal reason, which
    lands in the TRIGGERED_DARK branch of this function.

    Scope, honestly: in THAT run the same feature is also delivered and
    witnessed, so the projection reached WITNESSED anyway and the refusal
    changed no verdict (see
    ``test_full_real_row_set_projection_is_unchanged_by_the_budget_route``).
    The row shape is real; the RED it can cause is the case where a designed
    refusal is a feature's only evidence, which no local artifact exhibits.
    """
    rows = [{
        "event_type": "feature.evaluated",
        "payload": {
            "feature_id": "cochange_prior",
            "eligible": True,
            "outcome": "boundary_claim_ceiling",
        },
    }]

    summary = summarize_features(rows)

    assert summary["cochange_prior"]["status"] == "SUPPRESSED_WITH_REASON"
    assert summary["cochange_prior"]["reasons"] == ["boundary_claim_ceiling"]


def test_every_delivery_budget_reason_is_named_suppression():
    """The whole closed vocabulary routes, not only the reason seen in run
    35252797829."""
    from gt_engine.delivery_budget import DELIVERY_REFUSAL_REASONS

    for reason in sorted(DELIVERY_REFUSAL_REASONS):
        rows = [{
            "event_type": "feature.evaluated",
            "payload": {
                "feature_id": "newfile_precedent",
                "eligible": True,
                "outcome": reason,
            },
        }]

        summary = summarize_features(rows)

        assert summary["newfile_precedent"]["status"] == (
            "SUPPRESSED_WITH_REASON"
        ), reason
        assert summary["newfile_precedent"]["reasons"] == [reason]


def test_real_native_projection_of_a_budget_refusal_is_not_red():
    """End-to-end on the verbatim artifact row, through the audit projection."""
    from scripts.gt_audit import (
        _ATTRIBUTION_RED_STATUSES,
        _native_feature_projection,
    )

    refusal = {
        "action_index": 1,
        "admitted_bytes": 3324,
        "admitted_count": 4,
        "boundary_claim_limit": 4,
        "candidate_ordinal": 5,
        "dedup_key": "cochange-/testbed/aiogram/fsm/context.py-026f86de",
        "delivery_identity": "19b053b8dc39bdb8fcab05a89b7f464a3ca7215ac",
        "event": "delivery_refused",
        "iteration": 3,
        "kind": "cochange_partner",
        "lane": "sealed",
        "payload_sha256": "19b053b8dc39bdb8fcab05a89b7f464a3ca7215ac",
        "per_delivery_limit": 1400,
        "reason": "boundary_claim_ceiling",
        "rendered_bytes": 735,
        "request_byte_limit": 9600,
        "schema": "gt.event.v1",
        "sequence": 83,
        "target": "/testbed/aiogram/fsm/context.py",
    }

    projection = _native_feature_projection([refusal])

    assert projection["cochange_prior"]["status"] == "SUPPRESSED_WITH_REASON"
    assert (
        projection["cochange_prior"]["status"] not in _ATTRIBUTION_RED_STATUSES
    )


def test_non_budget_eligible_outcome_stays_triggered_dark():
    """The excuse must not widen: an outcome outside the vocabulary is dark."""
    rows = [{
        "event_type": "feature.evaluated",
        "payload": {
            "feature_id": "cochange_prior",
            "eligible": True,
            "outcome": "candidate_returned",
        },
    }]

    summary = summarize_features(rows)

    assert summary["cochange_prior"]["status"] == "TRIGGERED_DARK"
    assert summary["cochange_prior"]["reasons"] == ["candidate_returned"]


def test_eligible_outcome_absent_stays_triggered_dark():
    """An eligible trigger with no outcome at all is still dark."""
    rows = [{
        "event_type": "feature.evaluated",
        "payload": {"feature_id": "cochange_prior", "eligible": True},
    }]

    summary = summarize_features(rows)

    assert summary["cochange_prior"]["status"] == "TRIGGERED_DARK"
    assert summary["cochange_prior"]["reasons"] == ["producer_abstained"]


def test_producer_abstention_on_budget_reason_is_named_suppression():
    """The producer seam routes the same closed vocabulary, category or not.

    No producer.invocation row in the recorded gt_attribution.jsonl traces
    carries a delivery-budget reason - the runtime writes those to
    ``delivery_refused`` instead - so this route is defence in depth against a
    future producer that abstains on a budget it already knows it will hit.
    """
    rows = [{
        "event_type": "producer.invocation",
        "payload": {
            "outcome": "returned_nothing",
            "evidence_types": ["cochange_partner"],
            "abstention_reasons": [{
                "category": "",
                "detail": {},
                "reason": "boundary_claim_ceiling",
            }],
        },
    }]

    summary = summarize_features(rows)

    assert summary["cochange_prior"]["status"] == "SUPPRESSED_WITH_REASON"
    assert summary["cochange_prior"]["reasons"] == ["boundary_claim_ceiling"]


def test_producer_abstention_outside_budget_vocabulary_stays_dark():
    rows = [{
        "event_type": "producer.invocation",
        "payload": {
            "outcome": "returned_nothing",
            "evidence_types": ["cochange_partner"],
            "abstention_reasons": [{
                "category": "",
                "detail": {},
                "reason": "ranker_returned_empty",
            }],
        },
    }]

    summary = summarize_features(rows)

    assert summary["cochange_prior"]["status"] == "TRIGGERED_DARK"
    assert summary["cochange_prior"]["reasons"] == ["ranker_returned_empty"]


def test_producer_abstention_mixing_budget_and_stray_reasons_stays_dark():
    """One unexplained reason in the record keeps the whole record dark.

    The receipt orders the dark reason first: the finalisation folds the
    designed refusals in after every row, so the reason list reads
    "what went unexplained, then what was refused on purpose" in every
    record order (REVIEW-10 HIGH-1).
    """
    rows = [{
        "event_type": "producer.invocation",
        "payload": {
            "outcome": "returned_nothing",
            "evidence_types": ["cochange_partner"],
            "abstention_reasons": [
                {
                    "category": "",
                    "detail": {},
                    "reason": "boundary_claim_ceiling",
                },
                {
                    "category": "",
                    "detail": {},
                    "reason": "ranker_returned_empty",
                },
            ],
        },
    }]

    summary = summarize_features(rows)

    assert summary["cochange_prior"]["status"] == "TRIGGERED_DARK"
    assert summary["cochange_prior"]["reasons"] == [
        "ranker_returned_empty", "boundary_claim_ceiling"
    ]


def test_producer_abstention_with_no_reasons_is_unchanged():
    rows = [{
        "event_type": "producer.invocation",
        "payload": {
            "outcome": "returned_nothing",
            "evidence_types": ["cochange_partner"],
            "abstention_reasons": [],
        },
    }]

    summary = summarize_features(rows)

    assert summary["cochange_prior"]["status"] == "TRIGGERED_DARK"
    assert summary["cochange_prior"]["reasons"] == ["producer_abstained"]


def test_categorised_abstentions_keep_their_existing_routes():
    """The new route sits below the category ladder, not in front of it."""
    cases = [
        ("authority", "viewed_file_leaky", "SUPPRESSED_WITH_REASON"),
        ("dependency_failure", "graph_unavailable", "INELIGIBLE"),
        ("correct_quiet", "no_signature_change", "INELIGIBLE"),
        ("instrumentation_gap", "receipt_missing", "TELEMETRY_FAULT"),
    ]
    for category, reason, expected in cases:
        rows = [{
            "event_type": "producer.invocation",
            "payload": {
                "outcome": "returned_nothing",
                "evidence_types": ["cochange_partner"],
                "abstention_reasons": [
                    {"category": category, "detail": {}, "reason": reason},
                ],
            },
        }]

        summary = summarize_features(rows)

        assert summary["cochange_prior"]["status"] == expected, category


# --------------------------------------------------------------------------- #
# REVIEW-10 HIGH-1: the delivery-budget excuse must be a CONJUNCTION across
# every record for a feature, not a per-record verdict. ``summarize_features``
# takes the MAX over the priority ladder and CLEARS the reason list on a
# priority increase, so a per-record "budget reason -> SUPPRESSED_WITH_REASON"
# lets a designed refusal outrank, and therefore erase, a genuine dark fire
# recorded in another row. The tests below pin the invariant in every record
# order: a feature with ANY unexplained dark evidence stays TRIGGERED_DARK and
# keeps EVERY reason; only a feature whose sole dark-side evidence is designed
# refusals is named suppression.
# --------------------------------------------------------------------------- #

_DARK_EVALUATED = {
    "event_type": "feature.evaluated",
    "payload": {
        "feature_id": "cochange_prior",
        "eligible": True,
        "outcome": "ranker_returned_empty",
    },
}
_BUDGET_EVALUATED = {
    "event_type": "feature.evaluated",
    "payload": {
        "feature_id": "cochange_prior",
        "eligible": True,
        "outcome": "boundary_claim_ceiling",
    },
}


def test_dark_evaluation_alone_is_triggered_dark():
    """Control for the two orderings below: no budget row, nothing changes."""
    summary = summarize_features([_DARK_EVALUATED])

    assert summary["cochange_prior"]["status"] == "TRIGGERED_DARK"
    assert summary["cochange_prior"]["reasons"] == ["ranker_returned_empty"]


def test_dark_then_budget_keeps_the_dark_status_and_every_reason():
    """Dark first, then a designed refusal.

    The refusal must not promote the feature past the dark fire recorded a
    row earlier: at priority 2 it outranked TRIGGERED_DARK and ``update``
    cleared the reason list on the way up.
    """
    summary = summarize_features([_DARK_EVALUATED, _BUDGET_EVALUATED])

    assert summary["cochange_prior"]["status"] == "TRIGGERED_DARK"
    assert summary["cochange_prior"]["reasons"] == [
        "ranker_returned_empty", "boundary_claim_ceiling",
    ]


def test_budget_then_dark_keeps_the_dark_status_and_every_reason():
    """The reversed order must land on the identical receipt.

    This is the ordering that erased the dark reason outright: the budget row
    set SUPPRESSED_WITH_REASON (priority 2), then the dark row at priority 1
    could not raise the status, so ``update`` kept SUPPRESSED and the receipt
    reported a designed refusal for a feature that had also fired into the
    dark.
    """
    summary = summarize_features([_BUDGET_EVALUATED, _DARK_EVALUATED])

    assert summary["cochange_prior"]["status"] == "TRIGGERED_DARK"
    assert summary["cochange_prior"]["reasons"] == [
        "ranker_returned_empty", "boundary_claim_ceiling",
    ]


def test_budget_refusals_alone_are_named_suppression_sorted():
    """The isolation case still holds, and several refusals sort."""
    rows = [
        _BUDGET_EVALUATED,
        {
            "event_type": "feature.evaluated",
            "payload": {
                "feature_id": "cochange_prior",
                "eligible": True,
                "outcome": "delivery_byte_ceiling",
            },
        },
    ]

    summary = summarize_features(rows)

    assert summary["cochange_prior"]["status"] == "SUPPRESSED_WITH_REASON"
    assert summary["cochange_prior"]["reasons"] == [
        "boundary_claim_ceiling", "delivery_byte_ceiling",
    ]


def test_audit_conjunction_still_calls_a_mixed_feature_red():
    """The audit-side guard only inspects RED statuses.

    ``scripts.gt_audit.attribution_red_features`` excuses a feature only when
    EVERY reason is in the closed vocabulary, and it only looks at features in
    ``_ATTRIBUTION_RED_STATUSES``. Promoting a mixed feature to
    SUPPRESSED_WITH_REASON therefore bypassed that conjunction entirely
    instead of satisfying it.
    """
    from scripts.gt_audit import attribution_red_features

    for rows in (
        [_DARK_EVALUATED, _BUDGET_EVALUATED],
        [_BUDGET_EVALUATED, _DARK_EVALUATED],
    ):
        summary = summarize_features(rows)

        assert attribution_red_features(summary) == ["cochange_prior"]

    assert attribution_red_features(
        summarize_features([_BUDGET_EVALUATED])
    ) == []


def test_a_budget_refusal_never_demotes_a_delivered_feature():
    """The real-data shape: refused once, delivered elsewhere in the run.

    DELIVERED_UNEXPOSED (priority 3) must win in both record orders, and the
    refusal reason must still be on the receipt.
    """
    delivery = {
        "event_type": "decision.committed",
        "payload": {
            "decision": "delivered",
            "feature_id": "cochange_prior",
            "evidence_type": "cochange_partner",
            "delivery_id": "d-1",
            "reason": "native_seal_without_provider_identity_join",
        },
    }

    for rows in ([delivery, _BUDGET_EVALUATED], [_BUDGET_EVALUATED, delivery]):
        summary = summarize_features(rows)

        assert summary["cochange_prior"]["status"] == "DELIVERED_UNEXPOSED"
        assert "native_seal_without_provider_identity_join" in (
            summary["cochange_prior"]["reasons"]
        )
        assert "boundary_claim_ceiling" in summary["cochange_prior"]["reasons"]


def test_producer_budget_record_plus_a_dark_record_keeps_both():
    """The producer seam obeys the same finalisation across records."""
    producer_budget = {
        "event_type": "producer.invocation",
        "payload": {
            "outcome": "returned_nothing",
            "evidence_types": ["cochange_partner"],
            "abstention_reasons": [{
                "category": "",
                "detail": {},
                "reason": "boundary_claim_ceiling",
            }],
        },
    }

    for rows in (
        [producer_budget, _DARK_EVALUATED],
        [_DARK_EVALUATED, producer_budget],
    ):
        summary = summarize_features(rows)

        assert summary["cochange_prior"]["status"] == "TRIGGERED_DARK"
        assert summary["cochange_prior"]["reasons"] == [
            "ranker_returned_empty", "boundary_claim_ceiling",
        ]


def test_full_real_row_set_projection_keeps_heads_status_on_every_feature():
    """Replay one whole recorded trial, not the refusal rows in isolation.

    The round-1 verification fed only ``delivery_refused`` rows and concluded
    "43 rows, all SUPPRESSED". On the FULL row set of a trial the
    ``evidence_delivery`` rows carry the same features to DELIVERED_UNEXPOSED
    (priority 3) and beyond, so on this artifact the budget route moves no
    status: the map below is HEAD's, verbatim, and zero features differ.

    Precisely what is claimed, and no more (REVIEW-11 M-3): the STATUS is
    identical to HEAD's on every local artifact, and the reason lists are
    equal AS SETS - except that a designed refusal now survives onto a
    higher-status record in every arrival order, where HEAD kept it only when
    the refusal row happened to arrive last. The two divergent shapes are
    named and pinned in
    ``test_budget_route_is_order_independent_in_both_divergent_shapes``. This
    is not a no-op, and the value of the change is the invariant, not a delta
    on this artifact - the delta lives in
    ``tests/fixtures/attribution/refused_never_witnessed.events.jsonl``.

    Provenance: SWE-Live attestation run 35252797829, task
    aiogram__aiogram-1594, 682 native rows, 16 ``delivery_refused`` rows
    (9 localization_task_ceiling, 5 boundary_claim_ceiling,
    2 localization_fire_once). On that run the refused features
    (``localization``, ``cochange_prior``) are also delivered and witnessed,
    so they are WITNESSED with empty reasons under HEAD and here alike.

    This test is a LOCAL-ONLY EXTRA LAYER: the artifact is an untracked
    working-tree download, so it cannot run in CI and skips when absent. The
    CI coverage of the invariant is the tracked fixture tests below, which
    never skip.
    """
    from scripts.gt_audit import _native_feature_projection

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    candidates = sorted(
        repo_root.glob(
            ".tmp-swelive-attestation-35252797829/**/agent/events.jsonl"
        )
    )
    if not candidates:
        pytest.skip(
            "run 35252797829 artifact absent: it is an untracked local "
            "download, so this extra layer is local-only and never runs "
            "in CI. The invariant itself is covered by the tracked "
            "fixture tests below, which do not skip."
        )

    rows = [
        json.loads(line)
        for line in candidates[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    projection = _native_feature_projection(rows)

    head_status_map = {
        "GT_CERT_DELIVERY": "INELIGIBLE",
        "GT_CHANGE_SURFACE": "INELIGIBLE",
        "GT_EDIT_CHECK": "INELIGIBLE",
        "GT_HYPOTHESIS": "INELIGIBLE",
        "GT_LOC_RESLOT": "INELIGIBLE",
        "GT_PATCH_DELTA": "INELIGIBLE",
        "GT_SS_SUBMIT_RED": "INELIGIBLE",
        "caller_contract": "WITNESSED",
        "cochange_prior": "WITNESSED",
        "covering_red": "INELIGIBLE",
        "def_partition": "INELIGIBLE",
        "localization": "WITNESSED",
        "newfile_precedent": "WITNESSED",
        "obligations": "WITNESSED",
        "persistent_plan": "INELIGIBLE",
        "plan_gate": "INELIGIBLE",
        "recovery": "INELIGIBLE",
        "select_catalog": "WITNESSED",
        "signature_delta": "INELIGIBLE",
        "submit_refusal": "INELIGIBLE",
        "syntax_result": "INELIGIBLE",
    }
    observed = {
        feature_id: item["status"] for feature_id, item in projection.items()
    }
    differing = {
        feature_id
        for feature_id, status in observed.items()
        if head_status_map.get(feature_id) != status
    }

    assert differing == set()
    assert observed == head_status_map


# --------------------------------------------------------------------------- #
# REVIEW-11 M-3 / M-4: what this change actually does to the projection, and a
# fixture that exhibits the defect no local artifact exhibits.
# --------------------------------------------------------------------------- #

_ATTRIBUTION_FIXTURES = (
    pathlib.Path(__file__).resolve().parent / "fixtures" / "attribution"
)
_REFUSED_NEVER_WITNESSED = (
    _ATTRIBUTION_FIXTURES / "refused_never_witnessed.events.jsonl"
)


@functools.lru_cache(maxsize=1)
def _head_attribution_module():
    """HEAD's ``gt_engine/attribution.py``, executed as a standalone module.

    Returns ``None`` - never raises, never skips the caller's real work - when
    it cannot be had: no git binary, a shallow CI checkout with no blob, or a
    HEAD that already carries this change (once it lands, HEAD IS this code
    and comparing against it proves nothing). No assertion may therefore
    DEPEND on it; it strengthens a test, it never gates one, and every test
    below that uses it carries an equivalent assertion that always runs.

    HEAD's module has no relative imports, so exec-ing its source in a bare
    namespace is faithful.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    try:
        source = subprocess.run(
            ["git", "show", "HEAD:gt_engine/attribution.py"],
            cwd=repo_root, capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    if "DELIVERY_REFUSAL_REASONS" in source:
        return None
    module = types.ModuleType("head_gt_engine_attribution")
    module.__file__ = "HEAD:gt_engine/attribution.py"
    exec(
        compile(source, "HEAD:gt_engine/attribution.py", "exec"),
        module.__dict__,
    )
    return module


_RESURRECTION_DARK = {
    "event_type": "feature.evaluated",
    "payload": {
        "feature_id": "localization",
        "eligible": True,
        "outcome": "unexplained_miss",
    },
}
_RESURRECTION_BUDGET = {
    "event_type": "feature.evaluated",
    "payload": {
        "feature_id": "localization",
        "eligible": True,
        "outcome": "localization_fire_once",
    },
}
_RESURRECTION_DELIVERY = {
    "event_type": "decision.committed",
    "payload": {
        "decision": "delivered",
        "feature_id": "localization",
        "evidence_type": "localization",
        "delivery_id": "d-1",
        "reason": "sealed_and_delivered",
    },
}


def test_budget_route_is_order_independent_in_both_divergent_shapes():
    """The exact claim, replacing the round-2 "zero diff vs HEAD" wording.

    What is true: the STATUS is identical to HEAD's on every local artifact,
    and the reason lists are equal AS SETS - except that designed refusals now
    survive onto higher-status records in every arrival order. Two shapes
    diverge, both of them HEAD being order-dependent and this code not:

    1. reason ORDER, ``budget -> dark``: HEAD gave
       ``['localization_fire_once', 'unexplained_miss']`` while ``dark ->
       budget`` gave the reverse; here both orders give
       ``['unexplained_miss', 'localization_fire_once']`` - dark reasons
       first, in arrival order, then the refusals, sorted.
    2. reason RESURRECTION, ``budget -> delivered``: HEAD's ``update`` cleared
       the reason list on the priority increase, so a refusal that arrived
       before the delivery was erased (``['sealed_and_delivered']``) while
       ``delivered -> budget`` kept it. Here it survives in both orders, and
       that is the intended answer: a designed refusal that actually happened
       is evidence and belongs on the record whatever order the rows arrived
       in. The STATUS does not move - the higher priority still wins.

    Consumers read ``reasons`` as a set (``scripts/gt_live_gate.py:401``) and
    nothing hashes this projection, so neither divergence breaks a consumer.
    """
    dark_orders = [
        summarize_features([_RESURRECTION_BUDGET, _RESURRECTION_DARK]),
        summarize_features([_RESURRECTION_DARK, _RESURRECTION_BUDGET]),
    ]
    for summary in dark_orders:
        assert summary["localization"]["status"] == "TRIGGERED_DARK"
        assert set(summary["localization"]["reasons"]) == {
            "unexplained_miss", "localization_fire_once",
        }
    assert (
        dark_orders[0]["localization"]["reasons"]
        == dark_orders[1]["localization"]["reasons"]
        == ["unexplained_miss", "localization_fire_once"]
    )

    delivered_orders = [
        summarize_features([_RESURRECTION_BUDGET, _RESURRECTION_DELIVERY]),
        summarize_features([_RESURRECTION_DELIVERY, _RESURRECTION_BUDGET]),
    ]
    for summary in delivered_orders:
        assert summary["localization"]["status"] == "DELIVERED_UNEXPOSED"
        assert set(summary["localization"]["reasons"]) == {
            "sealed_and_delivered", "localization_fire_once",
        }
    assert (
        delivered_orders[0]["localization"]["reasons"]
        == delivered_orders[1]["localization"]["reasons"]
    )


def test_head_diverges_only_by_reason_order_and_the_erased_refusal():
    """Pin the two divergences against HEAD's real module, when loadable.

    Strengthening only: ``_head_attribution_module`` returns None on a shallow
    checkout or once this change has landed, and the order-independence this
    checks is already asserted unconditionally above.
    """
    head = _head_attribution_module()
    if head is None:
        pytest.skip(
            "HEAD blob unavailable (shallow checkout) or HEAD already carries "
            "this change; the invariant is asserted unconditionally by "
            "test_budget_route_is_order_independent_in_both_divergent_shapes"
        )

    shapes = {
        "budget->dark": [_RESURRECTION_BUDGET, _RESURRECTION_DARK],
        "dark->budget": [_RESURRECTION_DARK, _RESURRECTION_BUDGET],
        "budget->delivered": [_RESURRECTION_BUDGET, _RESURRECTION_DELIVERY],
        "delivered->budget": [_RESURRECTION_DELIVERY, _RESURRECTION_BUDGET],
    }
    head_result = {
        name: head.summarize_features(rows)["localization"]
        for name, rows in shapes.items()
    }
    ours = {
        name: summarize_features(rows)["localization"]
        for name, rows in shapes.items()
    }

    # Status: identical in every shape.
    for name in shapes:
        assert head_result[name]["status"] == ours[name]["status"], name

    # Divergence 1 - order only, set-equal.
    assert head_result["budget->dark"]["reasons"] == [
        "localization_fire_once", "unexplained_miss",
    ]
    assert ours["budget->dark"]["reasons"] == [
        "unexplained_miss", "localization_fire_once",
    ]
    assert set(head_result["budget->dark"]["reasons"]) == set(
        ours["budget->dark"]["reasons"]
    )
    assert (
        head_result["dark->budget"]["reasons"]
        == ours["dark->budget"]["reasons"]
    )

    # Divergence 2 - HEAD erased the refusal that arrived before the delivery.
    assert head_result["budget->delivered"]["reasons"] == [
        "sealed_and_delivered",
    ]
    assert ours["budget->delivered"]["reasons"] == [
        "sealed_and_delivered", "localization_fire_once",
    ]
    assert (
        head_result["delivered->budget"]["reasons"]
        == ours["delivered->budget"]["reasons"]
    )


def _refused_never_witnessed_rows() -> list[dict]:
    return [
        json.loads(line)
        for line in _REFUSED_NEVER_WITNESSED.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]


def test_refused_never_witnessed_fixture_has_the_shape_it_claims():
    """The fixture is hand-built and minimal: two rows, one of each seam.

    Hand-built on purpose - nothing is copied from a real run, there is no
    task text, and the only path is a placeholder - so the file identifies no
    task and no repository while still being a real ``gt.event.v1`` log.
    """
    from gt_engine.delivery_budget import DELIVERY_REFUSAL_REASONS

    rows = _refused_never_witnessed_rows()

    assert [row["event"] for row in rows] == [
        "evidence_delivery", "delivery_refused",
    ]
    assert all(row["schema"] == "gt.event.v1" for row in rows)
    refused = rows[1]
    assert refused["kind"] == "cochange_partner"
    assert feature_for_evidence(refused["kind"]) == "cochange_prior"
    assert refused["reason"] in DELIVERY_REFUSAL_REASONS
    # The whole point: the refused feature has no delivery and no witness
    # anywhere in the log.
    assert not [
        row for row in rows
        if row.get("event") == "evidence_delivery"
        and feature_for_evidence(row.get("kind")) == "cochange_prior"
    ]


def test_refusal_that_is_a_features_only_evidence_is_suppression_not_dark(
    monkeypatch,
):
    """The defect, on a fixture built because no local artifact exhibits it.

    Run 35252797829 shows the refusal SHAPE (16 ``delivery_refused`` rows,
    9 localization_task_ceiling / 5 boundary_claim_ceiling /
    2 localization_fire_once) but NOT the defect: there the refused features
    are also delivered and witnessed, so they reach WITNESSED with empty
    reasons under HEAD and here alike and the refusal decided no status. The
    invariant under test is synthetic by necessity - a feature whose ONLY
    dark-side evidence is a designed refusal must not be reported
    TRIGGERED_DARK.

    RED half, and it runs in CI with no git and no artifact: with the closed
    vocabulary emptied, ``summarize_features`` takes exactly the branch HEAD
    takes - ``mark_dark(feature_id, outcome or "producer_abstained")``, which
    is HEAD's ``update(feature_id, "TRIGGERED_DARK", outcome or
    "producer_abstained")`` verbatim, and the finalisation has nothing to fold
    in - so the refused-only feature comes back TRIGGERED_DARK.
    ``test_refused_never_witnessed_fixture_is_dark_under_heads_module``
    repeats it against HEAD's real module when the blob is available.
    """
    import gt_engine.attribution as attribution_module
    from scripts.gt_audit import _native_feature_projection

    rows = _refused_never_witnessed_rows()

    green = _native_feature_projection(rows)
    assert green["cochange_prior"]["status"] == "SUPPRESSED_WITH_REASON"
    assert green["cochange_prior"]["reasons"] == ["boundary_claim_ceiling"]
    assert green["caller_contract"]["status"] == "DELIVERED_UNEXPOSED"

    monkeypatch.setattr(
        attribution_module, "DELIVERY_REFUSAL_REASONS", frozenset()
    )
    red = _native_feature_projection(rows)
    assert red["cochange_prior"]["status"] == "TRIGGERED_DARK"
    assert red["cochange_prior"]["reasons"] == ["boundary_claim_ceiling"]
    assert red["caller_contract"]["status"] == "DELIVERED_UNEXPOSED"


def test_refused_never_witnessed_fixture_is_dark_under_heads_module(
    monkeypatch,
):
    """The same fixture through HEAD's real module, when the blob can be had.

    Strengthening only - the RED half is asserted unconditionally above by
    emptying the vocabulary, which drives the identical code path.
    """
    head = _head_attribution_module()
    if head is None:
        pytest.skip(
            "HEAD blob unavailable (shallow checkout) or HEAD already carries "
            "this change; the RED half runs unconditionally in "
            "test_refusal_that_is_a_features_only_evidence_is_suppression"
            "_not_dark"
        )

    import scripts.gt_audit as gt_audit

    rows = _refused_never_witnessed_rows()
    monkeypatch.setattr(
        gt_audit, "summarize_features", head.summarize_features
    )
    projection = gt_audit._native_feature_projection(rows)

    assert projection["cochange_prior"]["status"] == "TRIGGERED_DARK"
    assert projection["caller_contract"]["status"] == "DELIVERED_UNEXPOSED"
