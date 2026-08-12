#!/usr/bin/env python3
"""Consolidated fail-closed release gate for the central GT treatment.

This is an evidence gate, not a benchmark runner.  Provider-free gates produce
the ``static_evidence`` object and each task produces a central receipt.  The
gate joins those outputs and refuses release when any required substrate,
dense backend, delivery, preflight, or baseline-shield fact is absent.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from gt_engine.delivery_audit import audit_provider_deliveries
from gt_engine.runtime_gate import audit_runtime_receipt


@dataclass(frozen=True, slots=True)
class ReleaseGateCheck:
    name: str
    passed: bool
    failures: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReleaseGateReport:
    """Stable machine-readable release result (schema ``gt.release_gate.v1``)."""

    schema: str
    status: str
    receipts: int
    checks: tuple[ReleaseGateCheck, ...]
    failures: tuple[str, ...]
    summary: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.status == "READY"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status,
            "passed": self.passed,
            "receipts": self.receipts,
            "checks": [item.as_dict() for item in self.checks],
            "failures": list(self.failures),
            "summary": self.summary,
        }


def _bool(value: Any) -> bool:
    return value is True or value == 1 or str(value).strip().lower() in {
        "true",
        "ready",
        "passed",
        "pass",
        "approved",
        "smoke_approved",
    }


def _check_static(static: dict[str, Any] | None) -> ReleaseGateCheck:
    failures: list[str] = []
    if not isinstance(static, dict):
        return ReleaseGateCheck(
            "static_provider_free", False, ("missing_static_evidence",), {}
        )
    # These names intentionally accept the direct output names used by the
    # existing census/readiness/pre-smoke scripts.  Missing is never inferred
    # as pass.
    census_value = static.get("census_passed", static.get("census"))
    if isinstance(census_value, dict):
        census_value = census_value.get("status", census_value.get("passed"))
    readiness = static.get("readiness", static.get("central_readiness"))
    if isinstance(readiness, dict):
        readiness = readiness.get("status", readiness.get("passed"))
    smoke_value = static.get("pre_smoke_approved", static.get("smoke_approved"))
    if isinstance(smoke_value, dict):
        smoke_value = smoke_value.get("status", smoke_value.get("approved"))
    if not _bool(census_value):
        failures.append("census_not_passed")
    if not _bool(readiness):
        failures.append("readiness_not_ready")
    if not _bool(smoke_value):
        failures.append("pre_smoke_not_approved")
    if static.get("exact_commit") is not None and not _bool(static.get("exact_commit")):
        failures.append("exact_commit_not_pushed")
    return ReleaseGateCheck(
        "static_provider_free",
        not failures,
        tuple(failures),
        {"readiness": readiness, "keys": sorted(static)},
    )


def _substrate(receipt: dict[str, Any], label: str) -> ReleaseGateCheck:
    intelligence = receipt.get("repository_intelligence") or {}
    applicability = str(intelligence.get("applicability") or "")
    excluded = bool(intelligence.get("denominator_excluded"))
    failures: list[str] = []
    if excluded and applicability == "not_applicable_no_supported_source":
        return ReleaseGateCheck(
            "repository_substrate", True, (), {"applicability": applicability}
        )
    status = str(intelligence.get("status") or "")
    if status not in {"passed", "source_backed", "healthy", "available"}:
        failures.append(f"{label}:repository_status:{status or 'missing'}")
    if intelligence.get("failures"):
        failures.append(f"{label}:repository_failures_present")
    graph_gate = intelligence.get("graph_gate") or {}
    if graph_gate.get("blocked") is True:
        failures.append(f"{label}:graph_gate_blocked")
    metrics = receipt.get("metrics") or {}
    if intelligence.get("required") and int(metrics.get("repository_intelligence_valid") or 0) <= 0:
        failures.append(f"{label}:repository_intelligence_not_valid")
    return ReleaseGateCheck(
        "repository_substrate", not failures, tuple(failures),
        {"task": label, "status": status, "applicability": applicability},
    )


def _dense(receipt: dict[str, Any], label: str) -> ReleaseGateCheck:
    intelligence = receipt.get("repository_intelligence") or {}
    if (
        intelligence.get("denominator_excluded") is True
        and str(intelligence.get("applicability") or "")
        == "not_applicable_no_supported_source"
    ):
        return ReleaseGateCheck(
            "dense_backend",
            True,
            (),
            {"task": label, "applicability": "not_applicable_no_supported_source"},
        )
    retrieval = receipt.get("preemptive_retrieval") or {}
    backend = retrieval.get("dense_backend")
    failures: list[str] = []
    if not isinstance(backend, dict):
        failures.append(f"{label}:dense_backend_receipt_missing")
    else:
        if backend.get("available") is not True:
            failures.append(f"{label}:dense_backend_unavailable")
        if backend.get("failed") is True:
            failures.append(f"{label}:dense_backend_failed")
        if retrieval.get("dense_backend_error"):
            failures.append(f"{label}:dense_backend_error")
        legacy_identity = str(
            backend.get("backend_identity") or backend.get("model_revision") or ""
        )
        content_hashed_identity = (
            str(backend.get("backend") or "") == "snowflake_onnx"
            and bool(str(backend.get("model_name") or ""))
            and re.fullmatch(r"[0-9a-f]{64}", str(backend.get("model_sha256") or ""))
            is not None
        )
        if not legacy_identity and not content_hashed_identity:
            failures.append(f"{label}:dense_backend_identity_missing")
        if int(backend.get("network_calls") or 0) != 0:
            failures.append(f"{label}:dense_backend_network_calls")
        if int(backend.get("provider_calls") or 0) != 0:
            failures.append(f"{label}:dense_backend_provider_calls")
    return ReleaseGateCheck(
        "dense_backend", not failures, tuple(failures),
        {"task": label, "available": bool(isinstance(backend, dict) and backend.get("available"))},
    )


def _preflight(receipt: dict[str, Any], label: str) -> ReleaseGateCheck:
    metrics = receipt.get("metrics") or {}
    features = receipt.get("features") or {}
    rows = features.get("preflight_receipts") or []
    failures: list[str] = []
    if int(metrics.get("preflight_calls") or 0) != len(rows):
        failures.append(f"{label}:preflight_receipt_count_mismatch")
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            failures.append(f"{label}:preflight_malformed:{index}")
            continue
        decision = row.get("decision") or {}
        applied = str(row.get("applied_disposition") or "")
        disposition = str(decision.get("disposition") or "")
        if disposition == "pending" or applied == "pending":
            failures.append(f"{label}:preflight_pending:{index}")
        if applied == "" and int(metrics.get("preflight_calls") or 0):
            failures.append(f"{label}:preflight_unapplied:{index}")
    if int(metrics.get("preflight_duplicate_evidence") or 0) > 0:
        failures.append(f"{label}:preflight_duplicate_evidence")
    false_interventions = metrics.get("preflight_false_interventions")
    if isinstance(false_interventions, (int, float)) and false_interventions > 0:
        failures.append(f"{label}:preflight_false_interventions")
    return ReleaseGateCheck(
        "preflight_precision", not failures, tuple(failures),
        {"task": label, "calls": int(metrics.get("preflight_calls") or 0), "rows": len(rows)},
    )


def _decision_sufficiency(receipt: dict[str, Any], label: str) -> ReleaseGateCheck:
    runtime = receipt.get("decision_sufficiency") or {}
    if runtime.get("enabled") is not True:
        return ReleaseGateCheck(
            "decision_sufficiency",
            True,
            (),
            {"task": label, "enabled": False},
        )
    rows = runtime.get("decisions") or []
    preflight_calls = int((receipt.get("metrics") or {}).get("preflight_calls") or 0)
    failures: list[str] = []
    if len(rows) != preflight_calls:
        failures.append(f"{label}:decision_preflight_count_mismatch")
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            failures.append(f"{label}:decision_malformed:{index}")
            continue
        disposition = str(row.get("disposition") or "")
        if disposition not in {"pass", "return_eligible"}:
            failures.append(f"{label}:decision_disposition_invalid:{index}")
            continue
        if disposition != "return_eligible":
            continue
        bundle = row.get("bundle")
        if not isinstance(bundle, dict):
            failures.append(f"{label}:decision_bundle_missing:{index}")
            continue
        claims = bundle.get("claims") or []
        if (
            bundle.get("complete") is not True
            or len(claims) != 1
            or not str(bundle.get("source_revision") or "")
            or not str(bundle.get("graph_revision") or "")
            or str(bundle.get("selecting_request_hash") or "")
            != str(row.get("selecting_request_hash") or "")
        ):
            failures.append(f"{label}:decision_bundle_invalid:{index}")
        visible_ids = set(
            (row.get("retrieval") or {}).get("provider_visible_claim_ids") or []
        )
        if any(str(claim.get("claim_id") or "") in visible_ids for claim in claims):
            failures.append(f"{label}:decision_repeated_visible_claim:{index}")
        for claim in claims:
            if not str(claim.get("claim_id") or "") or not str(
                claim.get("decision_claim_id") or ""
            ):
                failures.append(f"{label}:decision_claim_identity_missing:{index}")
            support_kind = str(claim.get("support_kind") or "")
            if support_kind != "certified_structural":
                continue
            relation = str(claim.get("relation") or "").strip().lower()
            if relation not in {
                "calls",
                "inverse:calls",
                "asserted_by",
                "inverse:asserted_by",
            }:
                failures.append(f"{label}:decision_relation_not_material:{index}")
            provenance = tuple(str(item).lower() for item in claim.get("provenance") or ())
            if not any(
                item.startswith(("edge_endpoint_symbol:", "edge_endpoint_start:"))
                for item in provenance
            ):
                failures.append(f"{label}:decision_span_not_edge_aligned:{index}")
    return ReleaseGateCheck(
        "decision_sufficiency",
        not failures,
        tuple(failures),
        {"task": label, "enabled": True, "decisions": len(rows)},
    )


def _delivery(receipt: dict[str, Any], label: str) -> ReleaseGateCheck:
    runtime_failures, runtime_summary = audit_runtime_receipt(receipt, task=label)
    _rows, delivery_failures, delivery_summary = audit_provider_deliveries(
        receipt, task=label
    )
    failures = [*runtime_failures, *delivery_failures]
    return ReleaseGateCheck(
        "delivery_timing_accounting", not failures, tuple(failures),
        {"runtime": runtime_summary, "provider": delivery_summary},
    )


def _outcome_preservation(receipt: dict[str, Any], label: str) -> ReleaseGateCheck:
    """Require the four fail-open controls used by the frozen treatment."""

    configuration = receipt.get("component_configuration") or {}
    required = (
        "context_compaction",
        "completion_controller",
        "progress_control",
        "adaptive_validation_timeout",
    )
    failures = tuple(
        f"{label}:{name}_disabled"
        for name in required
        if configuration.get(name) is not True
    )
    return ReleaseGateCheck(
        "outcome_preservation_controls",
        not failures,
        failures,
        {
            "task": label,
            "configuration": {name: configuration.get(name) for name in required},
        },
    )


def _project_validation(receipt: dict[str, Any], label: str) -> ReleaseGateCheck:
    runtime = receipt.get("project_validation") or {}
    probes = runtime.get("probes") or []
    failures: list[str] = []
    seen_revisions: set[str] = set()
    for index, probe in enumerate(probes, start=1):
        revision = str(probe.get("source_revision") or "")
        if not revision:
            failures.append(f"{label}:project_probe_revision_missing:{index}")
        elif revision in seen_revisions:
            failures.append(f"{label}:project_probe_repeated_revision:{revision}")
        seen_revisions.add(revision)
        status = str(probe.get("status") or "")
        if status not in {"pass", "fail", "failed_open"}:
            failures.append(f"{label}:project_probe_status_invalid:{index}")
        if status == "fail" and not str(probe.get("diagnostic") or "").strip():
            failures.append(f"{label}:project_probe_failure_without_diagnostic:{index}")
    metrics = receipt.get("metrics") or {}
    if "project_validation_probe_attempts" in metrics and int(
        metrics.get("project_validation_probe_attempts") or 0
    ) != len(probes):
        failures.append(f"{label}:project_probe_count_mismatch")
    return ReleaseGateCheck(
        "project_validation",
        not failures,
        tuple(failures),
        {"task": label, "probes": len(probes)},
    )
def _retrieval_efficiency(receipt: dict[str, Any], label: str) -> ReleaseGateCheck:
    runtime = receipt.get("preemptive_retrieval") or {}
    if runtime.get("enabled") is False:
        return ReleaseGateCheck(
            "retrieval_efficiency",
            True,
            (),
            {"task": label, "enabled": False},
        )
    decisions = runtime.get("decisions") or []
    failures: list[str] = []
    for index, row in enumerate(decisions, start=1):
        if not str(row.get("opportunity_kind") or ""):
            failures.append(f"{label}:retrieval_opportunity_missing:{index}")
        reasons = set(row.get("reason_codes") or ())
        channels = row.get("channel_receipts") or []
        if reasons & {
            "task_character_budget",
            "task_character_budget_closed_precheck",
            "opportunity_budget_reserved_precheck",
        } and channels:
            failures.append(f"{label}:retrieval_work_after_budget_closed:{index}")
        if row.get("cache_hit") is True and any(
            float(channel.get("latency_ms") or 0.0) > 0.0 for channel in channels
        ):
            failures.append(f"{label}:retrieval_cache_hit_has_channel_latency:{index}")
    accounting = runtime.get("opportunity_accounting") or {}
    if decisions and (
        accounting.get("schema") != "gt.retrieval_opportunity_accounting.v1"
        or int(accounting.get("opportunities") or -1) != len(decisions)
    ):
        failures.append(f"{label}:retrieval_opportunity_accounting_invalid")
    metrics = receipt.get("metrics") or {}
    if int(metrics.get("preemptive_retrieval_duplicate_claims") or 0) > 0:
        failures.append(f"{label}:preemptive_duplicate_claims")
    return ReleaseGateCheck(
        "retrieval_efficiency",
        not failures,
        tuple(failures),
        {"task": label, "decisions": len(decisions)},
    )
def _baseline_shield(receipts: Iterable[dict[str, Any]]) -> ReleaseGateCheck:
    failures: list[str] = []
    count = 0
    for index, receipt in enumerate(receipts, start=1):
        count += 1
        label = f"off-{index}"
        if str(receipt.get("integration_mode") or "") != "off":
            failures.append(f"{label}:integration_mode_not_off")
        contexts = receipt.get("model_call_contexts") or []
        if not contexts:
            failures.append(f"{label}:missing_model_call_contexts")
        for call in contexts:
            if not isinstance(call, dict):
                failures.append(f"{label}:malformed_context")
                continue
            if call.get("provider_view_changed") is True:
                failures.append(f"{label}:provider_view_changed")
            stock = str(call.get("stock_provider_messages_sha256") or "")
            provider = str(call.get("provider_messages_sha256") or "")
            if not stock or not provider or stock != provider:
                failures.append(f"{label}:provider_view_not_stock_identical")
        metrics = receipt.get("metrics") or {}
        if int(metrics.get("provider_view_changed_calls") or 0) != 0:
            failures.append(f"{label}:provider_view_changed_metric")
    return ReleaseGateCheck(
        "baseline_shield", count > 0 and not failures, tuple(failures),
        {"off_receipts": count},
    )


def audit_treatment_runtime(
    receipt: dict[str, Any],
    *,
    label: str,
) -> tuple[ReleaseGateCheck, ...]:
    """Audit one treatment receipt without pretending an A/B control exists."""

    return (
        _substrate(receipt, label),
        _dense(receipt, label),
        _delivery(receipt, label),
        _preflight(receipt, label),
        _decision_sufficiency(receipt, label),
        _outcome_preservation(receipt, label),
        _project_validation(receipt, label),
        _retrieval_efficiency(receipt, label),
    )


def audit_release(
    receipts: Iterable[dict[str, Any]],
    *,
    static_evidence: dict[str, Any] | None = None,
    off_receipts: Iterable[dict[str, Any]] = (),
) -> ReleaseGateReport:
    treatment = list(receipts)
    off = list(off_receipts)
    checks: list[ReleaseGateCheck] = [_check_static(static_evidence)]
    if not treatment:
        checks.append(ReleaseGateCheck("treatment_receipts", False, ("no_treatment_receipts",), {}))
    for index, receipt in enumerate(treatment, start=1):
        label = f"treatment-{index}"
        checks.extend(audit_treatment_runtime(receipt, label=label))
    checks.append(_baseline_shield(off))
    failures = tuple(failure for check in checks for failure in check.failures)
    summary = {
        "treatment_receipts": len(treatment),
        "off_receipts": len(off),
        "checks_passed": sum(check.passed for check in checks),
        "checks_total": len(checks),
    }
    return ReleaseGateReport(
        "gt.release_gate.v1",
        "READY" if not failures and treatment else "BLOCKED",
        len(treatment), tuple(checks), failures, summary,
    )


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", action="append", type=Path, required=True)
    parser.add_argument("--off-receipt", action="append", type=Path, default=[])
    parser.add_argument("--static-evidence", type=Path, required=True)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    report = audit_release(
        [_load(path) for path in args.receipt],
        static_evidence=_load(args.static_evidence),
        off_receipts=[_load(path) for path in args.off_receipt],
    )
    rendered = json.dumps(report.as_dict(), indent=2, sort_keys=True)
    if args.json:
        args.json.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
