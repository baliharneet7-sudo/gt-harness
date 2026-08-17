"""Fail-closed integrity checks for a central GT runtime receipt.

These checks do not infer model usefulness from later actions.  They only prove
that the deterministic engine accounted for its work and that selected,
grounded retrieval was not silently dropped before the provider request.
"""

from __future__ import annotations

from typing import Any

_ACCOUNTED_COMPILER_STATUSES = frozenset(
    {
        "controller_state_considered",
        "existing_engine_actuation",
        "no_eligible_model_call",
        "provider_payload",
        "stale_state_rejected",
        "superseded_before_request",
    }
)


def _compiler_status_has_evidence(
    status: str,
    *,
    accountability: dict[str, Any],
    compiler: dict[str, Any],
) -> bool:
    """Return whether a compiler disposition has its required atomic proof."""

    if status == "provider_payload":
        delivery_ids = {
            str(item) for item in accountability.get("provider_delivery_ids") or () if str(item)
        }
        return bool(delivery_ids) and (
            str(compiler.get("provider_delivery_id") or "") in delivery_ids
        )
    if status == "existing_engine_actuation":
        return int(accountability.get("state_read_count") or 0) > 0
    if status == "controller_state_considered":
        return bool(
            compiler.get("request_payload_sha256")
            and compiler.get("fact_id")
            and int(compiler.get("first_considered_call") or 0) > 0
        )
    if status == "no_eligible_model_call":
        return bool(
            compiler.get("terminal") is True
            and compiler.get("eligible_model_calls_after_effect") == 0
        )
    if status == "stale_state_rejected":
        return bool(
            compiler.get("request_payload_sha256")
            and compiler.get("fact_id")
            and compiler.get("fact_disposition") == "stale_source_revision"
        )
    if status == "superseded_before_request":
        return bool(
            compiler.get("superseded_by_effect_id")
            and int(compiler.get("first_considered_call") or 0) > 0
        )
    return False


def normalized_effect_accountability(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve pending claims only when the compiler row carries atomic proof."""

    features = receipt.get("features") or {}
    rows = [
        dict(row)
        for row in features.get("effect_accountability") or ()
        if isinstance(row, dict)
    ]
    compiler_by_effect = {
        str(row.get("effect_id") or ""): dict(row)
        for row in features.get("context_compiler_effect_accountability") or ()
        if isinstance(row, dict) and row.get("effect_id")
    }
    for row in rows:
        if row.get("outcome") not in {
            "expired_unconsumed_claim",
            "pending_decision_claim",
        }:
            continue
        compiler = compiler_by_effect.get(str(row.get("effect_id") or ""), {})
        status = str(compiler.get("status") or "")
        if status in _ACCOUNTED_COMPILER_STATUSES and _compiler_status_has_evidence(
            status, accountability=row, compiler=compiler
        ):
            previous = str(row.get("outcome") or "")
            row["outcome"] = status
            row["normalized_from"] = previous
    return rows


def audit_runtime_receipt(
    receipt: dict[str, Any], *, task: str = "task"
) -> tuple[list[str], dict[str, int]]:
    metrics = receipt.get("metrics") or {}
    features = receipt.get("features")
    failures: list[str] = []

    def require(condition: bool, code: str) -> None:
        if not condition:
            failures.append(f"{task}:{code}")

    produced = int(metrics.get("effects_produced") or 0)
    applied = int(metrics.get("effects_applied") or 0)
    require(produced == applied, "effects_not_fully_applied")
    require(
        int(metrics.get("effect_trace_rows") or 0) == applied,
        "effect_trace_incomplete",
    )
    require(
        int(metrics.get("context_compiler_effects_unaccounted") or 0) == 0,
        "context_effect_unaccounted",
    )
    require(
        int(metrics.get("inert_private_state_effects") or 0) == 0,
        "inert_private_state_effect",
    )
    if isinstance(features, dict) and "effect_accountability" in features:
        raw_accountability = features.get("effect_accountability")
        raw_compiler = features.get("context_compiler_effect_accountability")
        if not isinstance(raw_accountability, list):
            failures.append(f"{task}:effect_accountability_malformed")
            raw_accountability = []
        if not isinstance(raw_compiler, list):
            failures.append(f"{task}:compiler_effect_accountability_malformed")
            raw_compiler = []
        malformed = sum(not isinstance(row, dict) for row in raw_accountability)
        if malformed:
            failures.append(f"{task}:effect_accountability_rows_malformed")
        malformed_compiler = sum(not isinstance(row, dict) for row in raw_compiler)
        if malformed_compiler:
            failures.append(f"{task}:compiler_effect_accountability_rows_malformed")
        account_rows = [row for row in raw_accountability if isinstance(row, dict)]
        compiler_rows = [row for row in raw_compiler if isinstance(row, dict)]
        effects = features.get("effects")
        applications = features.get("effect_applications")
        traces = features.get("effect_trace")
        for name, rows_value in (
            ("effects", effects),
            ("effect_applications", applications),
            ("effect_trace", traces),
        ):
            if not isinstance(rows_value, list) or any(
                not isinstance(row, dict) for row in rows_value
            ):
                failures.append(f"{task}:{name}_malformed")
        effect_rows = effects if isinstance(effects, list) else []
        application_rows = applications if isinstance(applications, list) else []
        trace_rows = traces if isinstance(traces, list) else []
        if len(effect_rows) != produced:
            failures.append(f"{task}:effect_row_count_mismatch")
        if len(application_rows) != applied:
            failures.append(f"{task}:effect_application_row_count_mismatch")
        if len(trace_rows) != int(metrics.get("effect_trace_rows") or 0):
            failures.append(f"{task}:effect_trace_row_count_mismatch")
        effect_ids = [str(row.get("effect_id") or "") for row in account_rows]
        compiler_ids = [str(row.get("effect_id") or "") for row in compiler_rows]
        if any(not effect_id for effect_id in effect_ids):
            failures.append(f"{task}:effect_id_missing")
        if len(effect_ids) != len(set(effect_ids)):
            failures.append(f"{task}:effect_id_duplicate")
        if len(compiler_ids) != len(set(compiler_ids)):
            failures.append(f"{task}:compiler_effect_id_duplicate")
        if len(account_rows) != produced:
            failures.append(f"{task}:effect_accountability_count_mismatch")
        if set(effect_ids) != set(compiler_ids):
            failures.append(f"{task}:compiler_effect_set_mismatch")
        serialized_effect_ids = {
            str(row.get("receipt_id") or "")
            for row in effect_rows
            if isinstance(row, dict)
        }
        application_effect_ids = {
            str(row.get("receipt_id") or "")
            for row in application_rows
            if isinstance(row, dict)
        }
        trace_effect_ids = {
            str(row.get("effect_id") or "")
            for row in trace_rows
            if isinstance(row, dict)
        }
        if any(
            ids != set(effect_ids)
            for ids in (
                serialized_effect_ids,
                application_effect_ids,
                trace_effect_ids,
            )
        ):
            failures.append(f"{task}:effect_ledger_foreign_key_mismatch")
        raw_pending = sum(
            row.get("outcome") == "pending_decision_claim" for row in account_rows
        )
        if raw_pending != int(metrics.get("pending_decision_claim_effects") or 0):
            failures.append(f"{task}:pending_effect_metric_mismatch")
        compiler_by_id = {
            str(row.get("effect_id") or ""): row for row in compiler_rows
        }
        for row in account_rows:
            outcome = str(row.get("outcome") or "")
            if outcome in _ACCOUNTED_COMPILER_STATUSES and not _compiler_status_has_evidence(
                outcome,
                accountability=row,
                compiler=compiler_by_id.get(str(row.get("effect_id") or ""), {}),
            ):
                failures.append(
                    f"{task}:effect_accountability_evidence_missing:"
                    f"{str(row.get('effect_id') or '')}"
                )
        normalized = normalized_effect_accountability(receipt)
        normalized_by_id = {
            str(row.get("effect_id") or ""): row for row in normalized
        }
        for row in account_rows:
            effect_id = str(row.get("effect_id") or "")
            if row.get("outcome") not in {
                "pending_decision_claim",
                "expired_unconsumed_claim",
            }:
                continue
            normalized_row = normalized_by_id.get(effect_id, row)
            if normalized_row.get("outcome") in {
                "pending_decision_claim",
                "expired_unconsumed_claim",
            }:
                failures.append(f"{task}:effect_accountability_evidence_missing:{effect_id}")
        require(
            not (
                (int(metrics.get("pending_decision_claim_effects") or 0) > 0 and not account_rows)
                or any(
                    row.get("outcome") == "pending_decision_claim" for row in normalized
                )
            ),
            "pending_decision_claim",
        )
    else:
        require(
            int(metrics.get("pending_decision_claim_effects") or 0) == 0,
            "pending_decision_claim",
        )

    prepared = int(metrics.get("provider_requests_prepared") or 0)
    coverage = float(metrics.get("provider_request_hash_coverage") or 0.0)
    require(not prepared or coverage == 1.0, "provider_request_hash_incomplete")
    require(int(metrics.get("late_payload_deliveries") or 0) == 0, "late_delivery")
    require(
        int(metrics.get("predictive_payload_deliveries") or 0) == 0,
        "predictive_delivery",
    )

    compiler = receipt.get("contribution_compiler") or {}
    for call in compiler.get("calls") or ():
        if not isinstance(call, dict):
            failures.append(f"{task}:malformed_contribution_call")
            continue
        require(
            int(call.get("candidate_count") or 0)
            == int(call.get("accounted_count") or 0),
            "contribution_accounting_mismatch",
        )

    retrieval = receipt.get("preemptive_retrieval") or {}
    decisions = [
        row for row in retrieval.get("decisions") or () if isinstance(row, dict)
    ]
    deliveries = [
        row for row in retrieval.get("deliveries") or () if isinstance(row, dict)
    ]
    compiler_calls = {
        int(row.get("call") or 0): row
        for row in compiler.get("calls") or ()
        if isinstance(row, dict)
    }
    selected = 0
    compiler_rejected = 0
    for decision in decisions:
        if (
            decision.get("status") == "abstained"
            and decision.get("retriever_status_before_contribution_compiler") == "selected"
            and decision.get("contribution_compiler_selected") is False
        ):
            compiler_rejected += 1
            require(
                bool(decision.get("contribution_compiler_disposition")),
                "preemptive_compiler_rejection_disposition_missing",
            )
            continue
        if decision.get("status") == "selected":
            call = int(decision.get("call") or 0)
            contribution = next(
                (
                    row
                    for row in (compiler_calls.get(call, {}).get("accounting") or ())
                    if isinstance(row, dict)
                    and row.get("surface") == "preemptive_retrieval"
                ),
                None,
            )
            if contribution and contribution.get("disposition") != "selected":
                compiler_rejected += 1
            selected += 1
            failures.append(f"{task}:preemptive_selected_not_delivered")
        elif decision.get("status") == "delivered":
            require(
                isinstance(decision.get("delivery_receipt"), dict),
                "preemptive_delivery_receipt_missing",
            )
    selected_evidence = int(
        metrics.get("preemptive_retrieval_selected_evidence") or 0
    )
    delivered_claims = int(
        metrics.get("preemptive_retrieval_claims_delivered") or 0
    )
    if selected_evidence and selected:
        require(delivered_claims > 0, "preemptive_selected_evidence_silent")
    require(
        int(metrics.get("preemptive_retrieval_deliveries") or 0)
        == len(deliveries),
        "preemptive_delivery_count_mismatch",
    )
    return failures, {
        "decisions": len(decisions),
        "selected_not_delivered": selected,
        "compiler_rejected": compiler_rejected,
        "deliveries": len(deliveries),
        "selected_evidence": selected_evidence,
        "delivered_claims": delivered_claims,
    }


__all__ = ["audit_runtime_receipt", "normalized_effect_accountability"]
