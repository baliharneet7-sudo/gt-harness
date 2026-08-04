#!/usr/bin/env python3
"""Executable trigger/payload census for the host-owned 17-feature runtime.

This is a producer test, not a claim that every real task triggers every
feature.  It exercises each boundary deliberately and rejects any delivery
whose payload is empty, stale, or attached to the wrong lifecycle boundary.
"""

from __future__ import annotations

import json

from gt_engine.central_runtime import (
    CENTRAL_FEATURE_IDS,
    CentralFeatureRuntime,
    WorkspaceTransition,
    feature_payload_grounded,
    feature_payload_valid,
)

EXPECTED_TIMING = {
    "obligations": ("task_start", (0,)),
    "localization": ("search_result", (1,)),
    "GT_LOC_RESLOT": ("search_result", (1,)),
    "def_partition": ("search_result", (1,)),
    "caller_contract": ("search_result", (1,)),
    "newfile_precedent": (("search_result", "edit_result"), (1, 2)),
    "GT_CHANGE_SURFACE": ("edit_result", (2,)),
    "GT_PATCH_DELTA": ("edit_result", (2,)),
    "signature_delta": ("edit_result", (2,)),
    # Delivery of signature_delta depends on its consumer being selected, not
    # on the producer alone; the one-message selection path currently discards
    # it in favor of the higher-priority syntax_result.  Consumer delivery is
    # proved by ALL_17_CONSUMERS_PROVEN, not by this producer timing row.
    "syntax_result": ("edit_result", (2,)),
    "GT_EDIT_CHECK": ("edit_result", (2,)),
    "covering_red": ("test_result", (3, 4)),
    "GT_HYPOTHESIS": ("test_result", (3, 4)),
    "recovery": ("test_result", (4,)),
    "submit_refusal": ("submit", (5,)),
    "GT_SS_SUBMIT_RED": ("submit", (5,)),
    "GT_CERT_DELIVERY": ("submit", (5,)),
}


def audit_timing(summary: dict) -> dict:
    """Judge payload, boundary, chronology, and visibility for every feature."""
    receipts = summary["receipts"]
    audit = {}
    for feature_id in CENTRAL_FEATURE_IDS:
        rows = [row for row in receipts if row["feature_id"] == feature_id]
        expected_boundary, expected_actions = EXPECTED_TIMING[feature_id]
        boundaries = (
            set(expected_boundary) if isinstance(expected_boundary, tuple) else {expected_boundary}
        )
        actual_actions = tuple(row["action"] for row in rows)
        payloads_valid = all(
            feature_payload_valid(
                feature_id,
                row["payload"],
                boundary=row["boundary"],
                revision=row["revision"],
                fresh=row["fresh"],
            )
            for row in rows
        )
        boundaries_valid = bool(rows) and all(row["boundary"] in boundaries for row in rows)
        actions_valid = actual_actions == expected_actions
        visibility_valid = all(
            row["model_visible"]
            == (
                row["decision"] == "DELIVERED"
                and feature_id
                in {
                    "covering_red",
                    "recovery",
                    "signature_delta",
                    "submit_refusal",
                    "syntax_result",
                }
            )
            for row in rows
        )
        audit[feature_id] = {
            "valid": payloads_valid and boundaries_valid and actions_valid and visibility_valid,
            "expected_boundary": expected_boundary,
            "actual_boundaries": [row["boundary"] for row in rows],
            "expected_actions": list(expected_actions),
            "actual_actions": list(actual_actions),
            "payloads_valid": payloads_valid,
            "visibility_valid": visibility_valid,
        }
    audit["_global"] = {
        "receipt_action_order_valid": [row["action"] for row in receipts]
        == sorted(row["action"] for row in receipts),
        "recovery_after_repeat": min(
            row["action"] for row in receipts if row["feature_id"] == "recovery"
        )
        > min(row["action"] for row in receipts if row["feature_id"] == "covering_red"),
        "submit_is_terminal_boundary": max(row["action"] for row in receipts) == 5,
    }
    audit["_global"]["valid"] = all(audit["_global"].values())
    return audit


def census() -> dict:
    runtime = CentralFeatureRuntime(model_visible=True)
    decision_windows = []

    def deliver_next(after_action: int) -> None:
        feedback = runtime.model_feedback(deferred=True)
        if not feedback:
            return
        metadata = runtime.confirm_prepared_guidance() or {}
        evidence_action = int(metadata.get("evidence_action") or 0)
        decision_windows.append(
            {
                "feature_id": metadata.get("feature_id"),
                "evidence_action": evidence_action,
                "prepared_after_action": after_action,
                "delivered_before_next_decision": True,
                "not_predictive": evidence_action <= after_action,
                "not_late": evidence_action == after_action,
                "chars": len(feedback),
            }
        )

    runtime.begin_task("Implement the requested change", revision="r0")
    runtime.observe_action(
        action_id=1,
        command="rg -n 'Bottle|caller' .",
        output=(
            "bottle.py:10:class Bottle\n"
            "tests/test_bottle.py:20:caller references Bottle; existing registry pattern\n"
        ),
        returncode=0,
        transition=WorkspaceTransition(1, "search", "r0", "r0"),
        revision="r0",
    )
    deliver_next(1)
    runtime.observe_action(
        action_id=2,
        command="sed -i 's/def f(/def f(x:/' app.py",
        output="def f(x: -> syntax error",
        returncode=0,
        transition=WorkspaceTransition(
            2,
            "edit",
            "r0",
            "r1",
            created=("new_module.py",),
            modified=("app.py",),
        ),
        revision="r1",
    )
    runtime.record_syntax(
        action_id=2,
        revision="r1",
        failed=True,
        reason="fixture_syntax_failure",
        path="app.py",
        command="python3 -m py_compile app.py",
        returncode=1,
        diagnostic="SyntaxError: invalid syntax",
    )
    deliver_next(2)
    for action_id in (3, 4):
        runtime.observe_action(
            action_id=action_id,
            command="pytest -q",
            output="1 failed: Error",
            returncode=1,
            transition=WorkspaceTransition(action_id, "test", "r1", "r1"),
            revision="r1",
        )
        deliver_next(action_id)
    runtime.record_submit(action_id=5, revision="r1", refused=True, sensor_healthy=True)
    deliver_next(5)
    summary = runtime.summary()
    summary["timing_audit"] = audit_timing(summary)
    summary["all_17_timing_valid"] = all(row["valid"] for row in summary["timing_audit"].values())
    summary["decision_window_audit"] = decision_windows
    summary["all_guidance_on_time"] = bool(decision_windows) and all(
        row["delivered_before_next_decision"] and row["not_predictive"] and row["not_late"]
        for row in decision_windows
    )
    summary["all_17_producers_proven"] = (
        summary["feature_count"] == 17
        and set(summary["feature_ids"]) == set(CENTRAL_FEATURE_IDS)
        and all(summary["produced_counts"][feature] >= 1 for feature in CENTRAL_FEATURE_IDS)
        and all(row["fresh"] and row["payload"].get("message") for row in summary["receipts"])
        and all(
            row["model_visible"]
            == (
                row["decision"] == "DELIVERED"
                and row["feature_id"]
                in {
                    "covering_red",
                    "recovery",
                    "signature_delta",
                    "submit_refusal",
                    "syntax_result",
                }
            )
            for row in summary["receipts"]
        )
        and summary["all_17_timing_valid"]
        and summary["all_guidance_on_time"]
    )
    consumer_paths = summary["consumer_paths"]
    summary["all_17_consumers_proven"] = bool(consumer_paths) and set(consumer_paths) >= set(
        CENTRAL_FEATURE_IDS
    )
    effects = summary["effects"]
    # Effect timing is non-vacuous: an empty effect set is a failure, not a
    # pass.  Full timing fields arrive with the consumer registry (Phase 3).
    summary["all_effects_timing_valid"] = bool(effects) and all(
        bool(row.get("evidence_before_effect"))
        and bool(row.get("effect_before_next_action"))
        and bool(row.get("non_late"))
        for row in effects
    )
    summary["all_payloads_semantically_grounded"] = bool(summary["receipts"]) and all(
        not row["model_visible"] or feature_payload_grounded(row["feature_id"], row["payload"])
        for row in summary["receipts"]
    )
    summary["all_17_consumer_paths_proven"] = (
        summary["all_17_producers_proven"]
        and summary["all_17_consumers_proven"]
        and summary["all_effects_timing_valid"]
        and summary["all_payloads_semantically_grounded"]
    )
    return summary


def main() -> int:
    result = census()
    print(json.dumps(result, indent=2, sort_keys=True))
    print(
        "ALL_17_PRODUCERS_PROVEN"
        if result["all_17_producers_proven"]
        else "PRODUCERS_NOT_PROVEN"
    )
    print(
        "ALL_17_CONSUMERS_PROVEN"
        if result["all_17_consumers_proven"]
        else "CONSUMERS_NOT_PROVEN"
    )
    print(
        "ALL_EFFECTS_TIMING_VALID"
        if result["all_effects_timing_valid"]
        else "EFFECTS_TIMING_INVALID"
    )
    print(
        "ALL_PAYLOADS_GROUNDED"
        if result["all_payloads_semantically_grounded"]
        else "PAYLOADS_NOT_GROUNDED"
    )
    print(
        "ALL_17_CONSUMER_PATHS_PROVEN"
        if result["all_17_consumer_paths_proven"]
        else "CONSUMER_PATHS_NOT_PROVEN"
    )
    return 0 if result["all_17_consumer_paths_proven"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
