"""Deterministic preflight rails for integrity and bounded convergence."""

from __future__ import annotations

import fnmatch
import hashlib
import posixpath
import re

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
    if any(
        normalized == root or normalized.startswith(root + "/")
        for root in _FORBIDDEN_ROOTS
    ):
        return True
    basename = posixpath.basename(normalized)
    return basename == "REF" or basename.lower() in _FORBIDDEN_LOWERCASE_BASENAMES


def _forbidden_search_selectors(proposed: ProposedAction) -> tuple[str, ...]:
    forbidden_names = ("logs", "solution", "REF", *_FORBIDDEN_LOWERCASE_BASENAMES)

    def targets_forbidden(option: str, selector: str) -> bool:
        pattern = selector.replace("\\/", "/").replace("\\.", ".")
        lowered_option = option.lower()
        root_names = tuple(root.lstrip("/") for root in _FORBIDDEN_ROOTS)
        basename_names = ("REF", *_FORBIDDEN_LOWERCASE_BASENAMES)
        path_samples = tuple(
            sample
            for root in root_names
            for sample in (root, f"{root}/sentinel", f"x/{root}/sentinel")
        ) + tuple(f"x/{name}" for name in basename_names)
        if lowered_option in {"-regex", "-iregex"}:
            literal_selector = (
                selector.replace("\\", "").replace("[", "").replace("]", "")
            )
            comparable = (
                literal_selector.lower()
                if lowered_option == "-iregex"
                else literal_selector
            )
            comparable_names = (
                tuple(name.lower() for name in basename_names)
                if lowered_option == "-iregex"
                else basename_names
            )
            comparable_roots = (
                tuple(root.lower() for root in root_names)
                if lowered_option == "-iregex"
                else root_names
            )
            if any(name in comparable for name in comparable_names) or any(
                f"/{root}" in comparable or f"{root}/" in comparable
                for root in comparable_roots
            ):
                return True
            flags = re.IGNORECASE if lowered_option == "-iregex" else 0
            try:
                compiled = re.compile(selector, flags)
            except re.error:
                compiled = None
            samples = tuple("/" + sample for sample in path_samples)
            if compiled is not None and any(
                compiled.fullmatch(sample) or compiled.search(sample)
                for sample in samples
            ):
                return True

        if lowered_option in {"-path", "-ipath", "-wholename", "-iwholename"}:
            candidate_pattern = pattern.lower() if lowered_option.startswith("-i") else pattern
            samples = (
                tuple(sample.lower() for sample in path_samples)
                if lowered_option.startswith("-i")
                else path_samples
            )
            if any(fnmatch.fnmatchcase(sample, candidate_pattern) for sample in samples):
                return True

        basename_pattern = posixpath.basename(pattern)
        if lowered_option in {"-iname", "-ipath", "-iwholename", "-iregex"}:
            basename_pattern = basename_pattern.lower()
        for name in forbidden_names:
            candidate = name.lower() if lowered_option.startswith("-i") else name
            if fnmatch.fnmatchcase(candidate, basename_pattern):
                return True

        components = tuple(part for part in pattern.split("/") if part)
        return any(
            fnmatch.fnmatchcase(root, component.lower())
            for component in components
            for root in ("logs", "solution")
        )

    forbidden: list[str] = []
    for operation in proposed.operations:
        for evidence in operation.parser_evidence:
            if not evidence.startswith("search_selector:"):
                continue
            payload = evidence.partition(":")[2]
            option, separator, selector = payload.partition(":")
            if not separator:
                option, selector = "", option
            if option.lower() not in {"-regex", "-iregex"}:
                selector = selector.replace("\\", "/")
            if targets_forbidden(option, selector) and selector not in forbidden:
                forbidden.append(selector)
    return tuple(forbidden)


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
    forbidden_selectors = _forbidden_search_selectors(proposed)
    if forbidden or forbidden_selectors:
        targets = (*forbidden, *forbidden_selectors)
        return _decision(
            proposed,
            source_revision=source_revision,
            reason="forbidden_benchmark_artifact_path",
            evidence=(
                "The selected action reads outside the task evidence boundary: "
                + ", ".join(targets[:2])
                + ". Use the task instruction, workspace source, and observed execution.",
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
