"""Deterministic preflight rails for integrity and bounded convergence."""

from __future__ import annotations

import hashlib
import posixpath
import re

from gt_engine.preflight import (
    ActionDisposition,
    EvidenceGrade,
    PreflightDecision,
    ProposedAction,
    pass_decision,
)

_FORBIDDEN_ROOTS = ("/logs", "/solution")
_FORBIDDEN_LOWERCASE_BASENAMES = frozenset(
    {"reward" + ".txt", "ctrf" + ".json", "test_outputs" + ".py"}
)
_STATIC_ASSIGNMENT_RE = re.compile(
    r"(?:^|[;&|]\s*)(?P<name>[A-Za-z_][A-Za-z0-9_]*)="
    r"(?P<quote>['\"]?)(?P<value>/[A-Za-z0-9_./-]+)(?P=quote)(?=\s|;|&|\||$)"
)
_PATH_LITERAL_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:/|\.\.?/)[A-Za-z0-9_./-]+"
)
_ACTIONABLE_PATH_ANCHOR = re.compile(
    r"^(?:/?[A-Za-z0-9_.-]+)(?:/[A-Za-z0-9_.-]+)*$"
)
_ACTIONABLE_CHECK_ANCHOR = re.compile(
    r"^(?:pytest|py\.test|ctest|go\s+test|cargo\s+test|npm\s+(?:test|run\s+test)|"
    r"pnpm\s+(?:test|run\s+test)|yarn\s+test|make\s+(?:test|check)|"
    r"python(?:3(?:\.\d+)?)?\s+-m\s+(?:pytest|unittest)|Rscript)\b",
    re.IGNORECASE,
)


def _paths(proposed: ProposedAction, *, cwd: str) -> tuple[str, ...]:
    assignments = {
        match.group("name"): posixpath.normpath(match.group("value"))
        for match in _STATIC_ASSIGNMENT_RE.finditer(proposed.raw_command)
    }

    def normalize(raw: str) -> str:
        value = raw.strip("'\"").replace("\\", "/")
        for name, replacement in assignments.items():
            value = value.replace("${" + name + "}", replacement)
            value = value.replace("$" + name, replacement)
        if value.startswith("/"):
            return posixpath.normpath(value)
        if value.startswith(("./", "../")):
            return posixpath.normpath(posixpath.join(cwd, value))
        return value

    values: list[str] = []
    for operation in proposed.operations:
        for target in operation.targets:
            raw = normalize(target.path)
            if raw and raw not in values:
                values.append(raw)
    for match in _PATH_LITERAL_RE.finditer(proposed.raw_command):
        raw = normalize(match.group(0).rstrip(".,:;"))
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
    def targets_forbidden(option: str, selector: str) -> bool:
        lowered_option = option.lower()
        ignore_case = lowered_option.startswith("-i")
        # A search selector is an integrity blocker only when it explicitly
        # names a forbidden root or basename.  Merely being broad enough to
        # match one (for example ``*.py`` or ``*.json``) is not evidence that
        # the selected action targets grader state.
        literal = (
            selector.replace("\\/", "/")
            .replace("\\.", ".")
            .replace("[.]", ".")
        )
        comparable = literal.lower() if ignore_case else literal
        basename_names = (
            ("ref", *_FORBIDDEN_LOWERCASE_BASENAMES)
            if ignore_case
            else ("REF", *_FORBIDDEN_LOWERCASE_BASENAMES)
        )
        for name in basename_names:
            if re.search(
                rf"(?<![A-Za-z0-9_.-]){re.escape(name)}(?![A-Za-z0-9_.-])",
                comparable,
            ):
                return True
        return bool(
            re.search(
                r"(?<![A-Za-z0-9_])(?:logs|solution)(?![A-Za-z0-9_])",
                comparable.lower(),
            )
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


def _actionable_anchor(value: str) -> bool:
    anchor = str(value or "").strip().strip("'\"")
    return bool(
        anchor
        and (
            (
                _ACTIONABLE_PATH_ANCHOR.fullmatch(anchor)
                and ("/" in anchor or "." in anchor)
            )
            or _ACTIONABLE_CHECK_ANCHOR.match(anchor)
        )
    )


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

    paths = _paths(proposed, cwd=posixpath.normpath(str(cwd or "/")))
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

    # Progress and budget state remain private controller signals.  Returning
    # broad-search advice here spends another provider decision and historically
    # caused harness-oriented exploration.  Only a proven evidence-boundary
    # violation is allowed to return an action from this controller.
    del progress_state, unresolved_anchors
    return pass_decision(proposed, "convergence_policy_pass")


__all__ = ["convergence_preflight"]
