"""Deterministic preflight rails for integrity and bounded convergence."""

from __future__ import annotations

import hashlib
import posixpath

from gt_engine.preflight import (
    ActionDisposition,
    ActionOperation,
    EvidenceGrade,
    PreflightDecision,
    ProposedAction,
    pass_decision,
)

_FORBIDDEN_ROOTS = ("/logs", "/solution")
_FORBIDDEN_LOWERCASE_BASENAMES = frozenset(
    {"reward" + ".txt", "ctrf" + ".json", "test_outputs" + ".py"}
)
_RISK_STATES = frozenset({"STALLED", "CONTRADICTED", "BUDGET_RISK"})


def _paths(proposed: ProposedAction) -> tuple[str, ...]:
    values: list[str] = []
    for operation in proposed.operations:
        for target in operation.targets:
            raw = target.path.strip("'\"").replace("\\", "/")
            if raw and raw not in values:
                values.append(raw)
    return tuple(values)


def _forbidden_path(path: str) -> bool:
    normalized = posixpath.normpath(path)
    if normalized == "/" or any(
        normalized == root or normalized.startswith(root + "/")
        for root in _FORBIDDEN_ROOTS
    ):
        return True
    basename = posixpath.basename(normalized)
    return basename == "REF" or basename.lower() in _FORBIDDEN_LOWERCASE_BASENAMES


def _decision(
    proposed: ProposedAction,
    *,
    source_revision: str,
    reason: str,
    evidence: tuple[str, ...],
) -> PreflightDecision:
    identity = hashlib.sha256(
        "\0".join((reason, *evidence, source_revision)).encode("utf-8", "replace")
    ).hexdigest()[:20]
    return PreflightDecision(
        disposition=ActionDisposition.RETURN_TO_MODEL,
        command=proposed.raw_command,
        evidence=evidence,
        reason_codes=(reason,),
        confidence=1.0,
        source_revision=source_revision,
        evidence_grade=EvidenceGrade.DIRECT,
        evidence_ids=("convergence-" + identity,),
    )


def convergence_preflight(
    proposed: ProposedAction,
    *,
    cwd: str,
    source_revision: str,
    progress_state: str = "",
    unresolved_anchors: tuple[str, ...] = (),
) -> PreflightDecision:
    """Return only mechanically certified integrity or convergence blockers."""

    paths = _paths(proposed)
    forbidden = tuple(path for path in paths if _forbidden_path(path))
    if forbidden:
        return _decision(
            proposed,
            source_revision=source_revision,
            reason="forbidden_benchmark_artifact_path",
            evidence=(
                "The proposed action targets a benchmark-harness or grader-only path: "
                + ", ".join(forbidden[:2])
                + ". Use only the task instruction, workspace, and observed task execution.",
            ),
        )

    root = posixpath.normpath(str(cwd or "/"))
    broad_search = bool(
        proposed.operation is ActionOperation.SEARCH
        and any(posixpath.normpath(path) in {"/", root} for path in paths)
    )
    if str(progress_state or "").upper() in _RISK_STATES and broad_search:
        anchors = tuple(str(item) for item in unresolved_anchors if str(item))[:2]
        suffix = (
            " Resolve or run: " + ", ".join(anchors) + "."
            if anchors
            else " Perform a focused validation or deliverable check."
        )
        return _decision(
            proposed,
            source_revision=source_revision,
            reason="convergence_budget_requires_verification",
            evidence=(
                "The trajectory is at deterministic budget risk; another workspace-wide "
                "search does not close an unresolved obligation." + suffix,
            ),
        )
    return pass_decision(proposed, "convergence_policy_pass")


__all__ = ["convergence_preflight"]
