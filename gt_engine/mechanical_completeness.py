"""Fail-closed per-call and per-task mechanical-completeness proofs.

This module does not claim that a stochastic model will solve a task.  It
proves the narrower product contract: every admitted provider request used a
complete, current, fully-accounted GT state and every terminal release check
for the task passed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

_SATISFIED = "SATISFIED"
_NOT_APPLICABLE = "PROVEN_NOT_APPLICABLE"
_FAILED = "FAILED"


def _requirement(
    requirement_id: str,
    *,
    satisfied: bool,
    failure: str,
    evidence: Mapping[str, Any],
    not_applicable: bool = False,
) -> tuple[dict[str, Any], str | None]:
    if not_applicable:
        status = _NOT_APPLICABLE
        failure_value = None
    elif satisfied:
        status = _SATISFIED
        failure_value = None
    else:
        status = _FAILED
        failure_value = failure
    return (
        {
            "requirement_id": requirement_id,
            "status": status,
            "evidence": dict(evidence),
        },
        failure_value,
    )


def _is_sha256(value: object) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def evaluate_provider_barrier(
    *,
    call: int,
    request_payload_sha256: str,
    provider_messages_sha256: str,
    source_snapshot_complete: bool,
    runtime_contract_ready: bool,
    task_semantic_ready: bool,
    graph_applicable: bool,
    graph_current: bool,
    repository_intelligence_ready: bool,
    retrieval_ready: bool,
    persistent_state_ready: bool,
    previous_actions_finalized: bool,
    context_candidate_count: int,
    context_accounted_count: int,
    contribution_candidate_count: int,
    contribution_accounted_count: int,
    replay_capture_enabled: bool,
) -> dict[str, Any]:
    """Evaluate the last host-owned barrier before a provider invocation."""

    requirements: list[dict[str, Any]] = []
    failures: list[str] = []

    def add(
        requirement_id: str,
        *,
        satisfied: bool,
        failure: str,
        evidence: Mapping[str, Any],
        not_applicable: bool = False,
    ) -> None:
        row, failed = _requirement(
            requirement_id,
            satisfied=satisfied,
            failure=failure,
            evidence=evidence,
            not_applicable=not_applicable,
        )
        requirements.append(row)
        if failed:
            failures.append(failed)

    add(
        "request_identity",
        satisfied=_is_sha256(request_payload_sha256),
        failure="request_identity_missing",
        evidence={"request_payload_sha256": request_payload_sha256},
    )
    add(
        "provider_view_identity",
        satisfied=_is_sha256(provider_messages_sha256),
        failure="provider_view_identity_missing",
        evidence={"provider_messages_sha256": provider_messages_sha256},
    )
    add(
        "runtime_contract",
        satisfied=bool(runtime_contract_ready),
        failure="runtime_contract_missing",
        evidence={"ready": bool(runtime_contract_ready)},
    )
    add(
        "task_semantic_substrate",
        satisfied=bool(task_semantic_ready),
        failure="task_semantic_substrate_not_ready",
        evidence={"ready": bool(task_semantic_ready)},
    )
    add(
        "source_snapshot_complete",
        satisfied=bool(source_snapshot_complete),
        failure="source_snapshot_incomplete",
        evidence={"complete": bool(source_snapshot_complete)},
    )
    add(
        "graph_current",
        satisfied=bool(graph_current),
        failure="graph_not_current",
        evidence={
            "applicable": bool(graph_applicable),
            "current": bool(graph_current),
        },
        not_applicable=not graph_applicable,
    )
    for requirement_id, ready, failure in (
        (
            "repository_intelligence",
            repository_intelligence_ready,
            "repository_intelligence_not_ready",
        ),
        ("retrieval", retrieval_ready, "retrieval_not_ready"),
        (
            "persistent_state",
            persistent_state_ready,
            "persistent_state_not_ready",
        ),
    ):
        add(
            requirement_id,
            satisfied=bool(ready),
            failure=failure,
            evidence={"applicable": bool(graph_applicable), "ready": bool(ready)},
            not_applicable=not graph_applicable,
        )
    add(
        "previous_action_finalized",
        satisfied=bool(previous_actions_finalized),
        failure="previous_action_not_finalized",
        evidence={"finalized": bool(previous_actions_finalized)},
    )
    add(
        "context_fact_accounting",
        satisfied=(
            int(context_candidate_count) == int(context_accounted_count)
            and int(context_candidate_count) >= 0
        ),
        failure="context_fact_accounting_mismatch",
        evidence={
            "candidate_count": int(context_candidate_count),
            "accounted_count": int(context_accounted_count),
        },
    )
    add(
        "contribution_accounting",
        satisfied=(
            int(contribution_candidate_count) == int(contribution_accounted_count)
            and int(contribution_candidate_count) >= 0
        ),
        failure="contribution_accounting_mismatch",
        evidence={
            "candidate_count": int(contribution_candidate_count),
            "accounted_count": int(contribution_accounted_count),
        },
    )
    add(
        "replay_capture",
        satisfied=bool(replay_capture_enabled),
        failure="replay_capture_disabled",
        evidence={"enabled": bool(replay_capture_enabled)},
    )
    return {
        "schema": "gt.provider_mechanical_barrier.v1",
        "call": int(call),
        "status": "PASS" if not failures else "BLOCKED",
        "requirements": requirements,
        "failures": failures,
    }


def build_task_execution_certificate(
    *,
    task: str,
    provider_barriers: Iterable[Mapping[str, Any]],
    dispatched_calls: int,
    release_checks: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Join live barriers and authoritative task release checks."""

    barriers = [dict(row) for row in provider_barriers]
    checks = [dict(row) for row in release_checks]
    failures: list[str] = []
    if len(barriers) != int(dispatched_calls):
        failures.append("provider_barrier_count_mismatch")
    for barrier in barriers:
        if barrier.get("status") != "PASS":
            failures.extend(str(item) for item in barrier.get("failures") or ())
    requirement_rows: list[dict[str, Any]] = []
    for check in checks:
        passed = check.get("passed") is True
        check_failures = [str(item) for item in check.get("failures") or ()]
        details = dict(check.get("details") or {})
        proven_not_applicable = bool(
            passed
            and (
                details.get("required") is False
                or details.get("applicability")
                == "not_applicable_no_supported_source"
            )
        )
        requirement_rows.append(
            {
                "requirement_id": str(check.get("name") or "unknown"),
                "status": (
                    _NOT_APPLICABLE
                    if proven_not_applicable
                    else _SATISFIED
                    if passed
                    else _FAILED
                ),
                "evidence": {
                    "failures": check_failures,
                    "details": details,
                },
            }
        )
        if not passed:
            failures.extend(check_failures or [f"{check.get('name')}:failed"])
    failed_count = sum(row["status"] == _FAILED for row in requirement_rows)
    pending_count = sum(
        row["status"] not in {_SATISFIED, _NOT_APPLICABLE, _FAILED}
        for row in requirement_rows
    )
    return {
        "schema": "gt.task_execution_certificate.v1",
        "task": str(task),
        "status": "PASS" if not failures and pending_count == 0 else "BLOCKED",
        "provider_barrier_count": len(barriers),
        "dispatched_provider_call_count": int(dispatched_calls),
        "provider_barriers": barriers,
        "requirements": requirement_rows,
        "pending_requirement_count": pending_count,
        "failed_requirement_count": failed_count,
        "failures": list(dict.fromkeys(failures)),
    }
