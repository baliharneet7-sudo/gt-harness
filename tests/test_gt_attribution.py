from __future__ import annotations

import json

from gt_engine.attribution import (
    DIRECT_FEATURES,
    AttributionTrace,
    summarize_features,
    verify_trace_rows,
)


def test_direct_feature_registry_is_exact_and_complete():
    facts = {name for name, spec in DIRECT_FEATURES.items() if spec["kind"] == "FACT"}
    caps = {name for name, spec in DIRECT_FEATURES.items() if spec["kind"] == "CAP"}

    assert facts == {
        "caller_contract",
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
    }
    assert len(DIRECT_FEATURES) == 17
    assert all(spec["boundaries"] for spec in DIRECT_FEATURES.values())
    assert all(spec["intended_action"] for spec in DIRECT_FEATURES.values())


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
            "event_type": "model.request",
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


def test_delivered_facts_witness_their_authoritative_capability_owners():
    owner_to_fact = {
        "GT_CHANGE_SURFACE": "newfile_precedent",
        "GT_PATCH_DELTA": "signature_delta",
        "GT_LOC_RESLOT": "localization",
        "GT_SS_SUBMIT_RED": "submit_refusal",
        "GT_EDIT_CHECK": "syntax_result",
        "GT_HYPOTHESIS": "recovery",
        "GT_CERT_DELIVERY": "submit_refusal",
    }
    rows = []
    for action_index, fact_id in enumerate(sorted(set(owner_to_fact.values())), 1):
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
                "event_type": "model.request",
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

    for capability, fact_id in owner_to_fact.items():
        assert summary[fact_id]["status"] == "WITNESSED"
        assert summary[capability]["status"] == "WITNESSED"
        assert summary[capability]["reasons"] == [f"delivered_{fact_id}"]


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
    ]
    assert summarize_features(rows)["GT_EDIT_CHECK"]["status"] == "WITNESSED"

    rows[0]["payload"].update({
        "eligible": False,
        "outcome": "no_edited_syntax_target",
    })
    assert summarize_features(rows)["GT_EDIT_CHECK"]["status"] == "INELIGIBLE"


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
