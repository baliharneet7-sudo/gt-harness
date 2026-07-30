"""Deterministic, content-safe attribution records for the GT engine.

The delivery ledger proves that bytes were sealed. This trace answers the
different questions needed for mechanism attribution: what boundary GT saw,
why a decision stayed quiet, and which delivered evidence was present in the
request that produced a model response.

Raw prompts, tool output, model text, and provider payloads are never persisted
here. Content-bearing events store only a byte hash and character count.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

DIRECT_FEATURES: dict[str, dict[str, Any]] = {
    "caller_contract": {
        "kind": "FACT", "boundaries": ("file_view", "edit_result"),
        "intended_action": "update or inspect proven callers",
    },
    "covering_red": {
        "kind": "FACT", "boundaries": ("edit_result", "submit"),
        "intended_action": "repair an attributable covering-test regression",
    },
    "def_partition": {
        "kind": "FACT", "boundaries": ("search_result",),
        "intended_action": "distinguish definitions from references",
    },
    "localization": {
        "kind": "FACT", "boundaries": ("task_start", "search_result"),
        "intended_action": "inspect ranked relevant source locations",
    },
    "newfile_precedent": {
        "kind": "FACT", "boundaries": ("edit_result",),
        "intended_action": "follow a verified repository precedent for a new file",
    },
    "obligations": {
        "kind": "FACT", "boundaries": ("task_start",),
        "intended_action": "satisfy issue-derived requirements",
    },
    "recovery": {
        "kind": "FACT", "boundaries": ("test_result", "tool_result"),
        "intended_action": "form a new hypothesis after a falsified edit",
    },
    "signature_delta": {
        "kind": "FACT", "boundaries": ("edit_result",),
        "intended_action": "repair call sites affected by a signature change",
    },
    "submit_refusal": {
        "kind": "FACT", "boundaries": ("submit",),
        "intended_action": "resolve positive failing evidence before submission",
    },
    "syntax_result": {
        "kind": "FACT", "boundaries": ("submit",),
        "intended_action": "repair an executed syntax failure",
    },
    "GT_CERT_DELIVERY": {
        "kind": "CAP", "boundaries": ("submit",),
        "intended_action": "name the evidence state of the completion decision",
    },
    "GT_CHANGE_SURFACE": {
        "kind": "CAP", "boundaries": ("search_result",),
        "intended_action": "identify the proven change surface",
    },
    "GT_EDIT_CHECK": {
        "kind": "CAP", "boundaries": ("edit_result", "submit"),
        "intended_action": "validate edited code with deterministic checks",
    },
    "GT_HYPOTHESIS": {
        "kind": "CAP", "boundaries": ("test_result", "tool_result"),
        "intended_action": "track repeated failures across edits",
    },
    "GT_LOC_RESLOT": {
        "kind": "CAP", "boundaries": ("search_result",),
        "intended_action": "reslot a ranked localization result into the request",
    },
    "GT_PATCH_DELTA": {
        "kind": "CAP", "boundaries": ("edit_result",),
        "intended_action": "derive evidence from the actual before/after patch",
    },
    "GT_SS_SUBMIT_RED": {
        "kind": "CAP", "boundaries": ("submit",),
        "intended_action": "refuse once after an observed unresolved test failure",
    },
}

_EVIDENCE_FEATURES = {
    "caller_contract": "caller_contract",
    "caller_contract_view": "caller_contract",
    "covering_red": "covering_red",
    "covering_verdict": "covering_red",
    "def_partition": "def_partition",
    "def_ref_partition": "def_partition",
    "localization": "localization",
    "ranked_localization": "localization",
    "new_file_destination": "newfile_precedent",
    "newfile_precedent": "newfile_precedent",
    "obligations": "obligations",
    "recovery": "recovery",
    "caller_break": "caller_contract",
    "signature_mismatch": "signature_delta",
    "signature_delta": "signature_delta",
    "submit_refusal": "submit_refusal",
    "syntax_result": "syntax_result",
}


def feature_for_evidence(evidence_type: str | None) -> str | None:
    """Map a concrete envelope type to its 17-feature census identity."""
    return _EVIDENCE_FEATURES.get(str(evidence_type or ""))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


class AttributionTrace:
    """Append-only, hash-chained JSONL trace.

    Writes are correct-or-quiet: tracing can never break the engine path.
    """

    def __init__(
        self,
        path_provider: Callable[[], Path | str | None],
        *,
        trace_id: str | None = None,
    ) -> None:
        self._path_provider = path_provider
        self.trace_id = trace_id or uuid.uuid4().hex
        self.sequence = 0
        self.previous_hash = ""
        self.rows: list[dict[str, Any]] = []

    def record(
        self,
        event_type: str,
        *,
        action_index: int,
        boundary: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.sequence += 1
        row: dict[str, Any] = {
            "version": "gt.attribution.v1",
            "trace_id": self.trace_id,
            "sequence": self.sequence,
            "event_type": str(event_type),
            "action_index": int(action_index),
            "boundary": str(boundary),
            "payload": dict(payload or {}),
            "previous_hash": self.previous_hash,
        }
        row["row_hash"] = hashlib.sha256(_canonical_bytes(row)).hexdigest()
        self.previous_hash = row["row_hash"]
        self.rows.append(row)
        try:
            path_value = self._path_provider()
            if path_value:
                path = Path(path_value)
                with path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(
                        row, sort_keys=True, ensure_ascii=False,
                    ) + "\n")
                    handle.flush()
        except Exception:  # noqa: BLE001 - telemetry must never break execution
            pass
        return row

    def record_content(
        self,
        event_type: str,
        *,
        content: str | None,
        action_index: int,
        boundary: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = content or ""
        safe_payload = dict(payload or {})
        safe_payload["content_chars"] = len(text)
        safe_payload["content_sha256"] = hashlib.sha256(
            text.encode("utf-8", "surrogatepass"),
        ).hexdigest()
        return self.record(
            event_type,
            action_index=action_index,
            boundary=boundary,
            payload=safe_payload,
        )


def census_trace_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the rich summary in stable registry order for the submit row."""
    summary = summarize_features(rows)
    return [
        {"feature_id": feature_id, **summary[feature_id]}
        for feature_id in DIRECT_FEATURES
    ]


def verify_trace_rows(rows: Iterable[dict[str, Any]]) -> list[str]:
    """Return deterministic integrity errors for already parsed trace rows."""
    issues: list[str] = []
    previous_hash = ""
    trace_id: str | None = None
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            issues.append(f"row {position}: not an object")
            continue
        if row.get("sequence") != position:
            issues.append(f"row {position}: sequence mismatch")
        if trace_id is None:
            trace_id = str(row.get("trace_id", ""))
        elif str(row.get("trace_id", "")) != trace_id:
            issues.append(f"row {position}: trace_id mismatch")
        if str(row.get("previous_hash", "")) != previous_hash:
            issues.append(f"row {position}: previous_hash mismatch")
        claimed_hash = str(row.get("row_hash", ""))
        unhashed = {key: value for key, value in row.items() if key != "row_hash"}
        expected_hash = hashlib.sha256(_canonical_bytes(unhashed)).hexdigest()
        if claimed_hash != expected_hash:
            issues.append(f"row {position}: row_hash mismatch")
        previous_hash = claimed_hash
    return issues


def summarize_features(
    rows: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build a conservative 17-feature projection from attribution events.

    Exact-byte exposure and response linkage are observable. Semantic
    consumption and causal benefit are intentionally not inferred here.
    """
    materialized = [dict(row) for row in rows]
    summary: dict[str, dict[str, Any]] = {
        feature_id: {
            "kind": spec["kind"],
            "status": "INELIGIBLE",
            "reasons": ["no_trigger_observed"],
            "deliveries": [],
            "exposed": False,
            "response_observed": False,
        }
        for feature_id, spec in DIRECT_FEATURES.items()
    }

    priority = {
        "INELIGIBLE": 0,
        "TRIGGERED_DARK": 1,
        "SUPPRESSED_WITH_REASON": 2,
        "DELIVERED_UNEXPOSED": 3,
        "EXPOSED": 4,
        "WITNESSED": 5,
        # A witnessed delivery cannot excuse a broken causal trace elsewhere
        # in the same feature. Audit integrity outranks lifecycle success.
        "TELEMETRY_FAULT": 6,
    }

    def update(feature_id: str, status: str, reason: str = "") -> None:
        if feature_id not in summary:
            return
        previous_status = summary[feature_id]["status"]
        if priority[status] > priority[previous_status]:
            summary[feature_id]["status"] = status
            summary[feature_id]["reasons"] = []
        elif priority[status] == priority[previous_status]:
            summary[feature_id]["status"] = status
        if reason:
            if summary[feature_id]["reasons"] == ["no_trigger_observed"]:
                summary[feature_id]["reasons"] = []
            if reason not in summary[feature_id]["reasons"]:
                summary[feature_id]["reasons"].append(reason)

    delivery_to_feature: dict[str, str] = {}
    delivered_features: list[str] = []
    exposed_ids: set[str] = set()
    response_ids: set[str] = set()
    producer_terminal_ids = {
        str(row.get("payload", {}).get("invocation_id") or "")
        for row in materialized
        if row.get("event_type") == "producer.invocation"
        and row.get("payload", {}).get("outcome") != "entered"
    }
    for row in materialized:
        event_type = str(row.get("event_type") or "")
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        if event_type == "model.request":
            exposed_ids.update(str(item) for item in payload.get("delivery_ids", ()))
            continue
        if event_type == "model.response":
            response_ids.update(str(item) for item in payload.get("delivery_ids", ()))
            continue
        if event_type == "decision.committed":
            evidence_type = str(payload.get("evidence_type") or "")
            feature_id = str(
                payload.get("feature_id") or feature_for_evidence(evidence_type) or ""
            )
            decision = str(payload.get("decision") or "")
            reason = str(payload.get("reason") or "")
            if decision == "delivered" and feature_id:
                delivery_id = str(payload.get("delivery_id") or "")
                update(
                    feature_id,
                    "DELIVERED_UNEXPOSED",
                    reason or "sealed_and_delivered",
                )
                if delivery_id:
                    delivery_to_feature[delivery_id] = feature_id
                    summary[feature_id]["deliveries"].append(delivery_id)
                delivered_features.append(feature_id)
            elif decision == "suppressed" and feature_id:
                update(feature_id, "SUPPRESSED_WITH_REASON", reason or "suppressed")
            continue
        if event_type == "feature.evaluated":
            feature_id = str(payload.get("feature_id") or "")
            if bool(payload.get("eligible")):
                outcome = str(payload.get("outcome") or "")
                if (
                    feature_id == "GT_EDIT_CHECK"
                    and outcome in {"ok", "pass"}
                ):
                    update(feature_id, "WITNESSED", outcome)
                    continue
                update(
                    feature_id,
                    "TRIGGERED_DARK",
                    outcome or "producer_abstained",
                )
            else:
                update(
                    feature_id,
                    "INELIGIBLE",
                    str(payload.get("outcome") or "trigger_not_satisfied"),
                )
            continue
        if event_type == "producer.invocation":
            outcome = str(payload.get("outcome") or "")
            feature_ids = {
                mapped
                for mapped in (
                    feature_for_evidence(str(item))
                    for item in payload.get("evidence_types", ())
                )
                if mapped
            }
            if outcome == "entered":
                invocation_id = str(payload.get("invocation_id") or "")
                if invocation_id not in producer_terminal_ids:
                    for feature_id in feature_ids:
                        update(
                            feature_id,
                            "TELEMETRY_FAULT",
                            "producer_terminal_missing",
                        )
                continue
            reasons = payload.get("abstention_reasons", ())
            categories = {
                str(item.get("category") or "")
                for item in reasons
                if isinstance(item, dict)
            }
            reason_names = [
                str(item.get("reason") or "")
                for item in reasons
                if isinstance(item, dict) and str(item.get("reason") or "")
            ]
            for feature_id in feature_ids:
                if outcome == "returned_fact":
                    update(feature_id, "TRIGGERED_DARK", "candidate_returned")
                elif "instrumentation_gap" in categories or outcome == "fault":
                    update(
                        feature_id,
                        "TELEMETRY_FAULT",
                        reason_names[0] if reason_names else "producer_audit_fault",
                    )
                elif categories & {
                    "authority",
                    "registry",
                    "dedup",
                    "cooldown",
                    "suppression",
                }:
                    for reason in reason_names or ["authority_suppressed"]:
                        update(feature_id, "SUPPRESSED_WITH_REASON", reason)
                elif categories and categories <= {
                    "correct_quiet", "dependency_failure"
                }:
                    for reason in reason_names or ["required_input_absent"]:
                        update(feature_id, "INELIGIBLE", reason)
                else:
                    for reason in reason_names or ["producer_abstained"]:
                        update(feature_id, "TRIGGERED_DARK", reason)
            continue
        if event_type == "control.decision":
            feature_id = str(payload.get("feature_id") or "")
            decision = str(payload.get("decision") or "")
            reason = str(payload.get("reason") or decision or "control_evaluated")
            if decision == "APPLIED":
                update(feature_id, "WITNESSED", reason)
            elif decision in {"SUPPRESSED", "DROPPED"}:
                update(feature_id, "SUPPRESSED_WITH_REASON", reason)
            elif decision == "ERROR":
                update(feature_id, "TELEMETRY_FAULT", reason)
            elif feature_id:
                update(feature_id, "INELIGIBLE", reason)

    for delivery_id, feature_id in delivery_to_feature.items():
        summary[feature_id]["exposed"] = (
            summary[feature_id]["exposed"] or delivery_id in exposed_ids
        )
        summary[feature_id]["response_observed"] = (
            summary[feature_id]["response_observed"]
            or delivery_id in response_ids
        )
        if delivery_id in response_ids:
            update(feature_id, "WITNESSED")
        elif delivery_id in exposed_ids:
            update(feature_id, "EXPOSED")
    fact_caps = {
        "newfile_precedent": ("GT_CHANGE_SURFACE",),
        "localization": ("GT_LOC_RESLOT",),
        "recovery": ("GT_HYPOTHESIS",),
        "signature_delta": ("GT_PATCH_DELTA",),
        "submit_refusal": ("GT_SS_SUBMIT_RED", "GT_CERT_DELIVERY"),
        "syntax_result": ("GT_EDIT_CHECK",),
    }
    for feature_id in delivered_features:
        for cap in fact_caps.get(feature_id, ()):
            update(cap, "WITNESSED", f"delivered_{feature_id}")
    return summary
