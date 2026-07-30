"""Executable, conservative verification predicates for task obligations."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from gt_engine.task_contract import (
    TaskContract,
    matching_obligation_ids,
    significant_tokens,
)

_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?:\s*(?:ms|s|m|mb|gb|%))?")
_PATH_RE = re.compile(
    r"(?<![\w.-])(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9_]+"
)
_CONTENT_RE = re.compile(
    r"(?i)\b(?:secret|sensitive|token|credential|api key|not present|"
    r"none remain|remove all|sanitize|placeholder)\b"
)
_NUMERIC_RE = re.compile(
    r"(?i)(?:<=|>=|<|>|below|above|threshold|at most|at least|less than|"
    r"more than|\d+(?:\.\d+)?\s*(?:ms|s|m|mb|gb|%))"
)
_ARTIFACT_RE = re.compile(
    r"(?i)\b(?:create|generate|produce|write|put it in|artifact|file)\b"
)
_EXECUTABLE_RE = re.compile(
    r"(?i)\b(?:pytest|unittest|npm\s+test|cargo\s+test|go\s+test|"
    r"assert|check|verify|validate|test\s+-[ef]|compile|build|import)\b"
)
_FULL_SUITE_RE = re.compile(
    r"(?i)(?:^|[;&|]\s*)(?:python\s+-m\s+pytest|pytest|npm\s+test|"
    r"cargo\s+test|go\s+test\s+\./\.\.\.)\s*(?:-[a-zA-Zqvxrs]+\s*)*$"
)
_SCOPE_EXCLUSION_RE = re.compile(
    r"(?i)(?:grep\s+-v|--exclude|--exclude-dir|-path\s+\S+\s+-prune)"
)


@dataclass(frozen=True)
class ObligationPredicate:
    predicate_id: str
    obligation_id: str
    kind: str
    scope: tuple[str, ...] = ()
    anchors: tuple[str, ...] = ()


@dataclass(frozen=True)
class PredicateReceipt:
    predicate_id: str
    obligation_id: str
    kind: str
    outcome: str
    command_sha256: str
    output_sha256: str
    action_index: int


def compile_obligation_predicates(
    contract: TaskContract,
) -> dict[str, ObligationPredicate]:
    """Compile one conservative primary predicate for every obligation."""
    compiled: dict[str, ObligationPredicate] = {}
    for item in contract.obligations:
        text = str(item.text or "")
        paths = tuple(sorted(set(_PATH_RE.findall(text))))
        if contract.role == "content_scan" or _CONTENT_RE.search(text):
            kind = "content_scope"
        elif _NUMERIC_RE.search(text):
            kind = "numeric_threshold"
        elif paths and _ARTIFACT_RE.search(text):
            kind = "artifact"
        else:
            kind = "behavior"
        digest = hashlib.sha256(
            f"{item.obligation_id}\0{kind}".encode()
        ).hexdigest()[:16]
        compiled[item.obligation_id] = ObligationPredicate(
            predicate_id=f"pred-{digest}",
            obligation_id=item.obligation_id,
            kind=kind,
            scope=paths,
            anchors=significant_tokens(text),
        )
    return compiled


def is_full_repository_suite(command: str) -> bool:
    return bool(_FULL_SUITE_RE.search((command or "").strip()))


def evaluate_passing_observation(
    contract: TaskContract,
    predicates: dict[str, ObligationPredicate],
    command: str,
    output: str,
    *,
    action_index: int,
) -> tuple[PredicateReceipt, ...]:
    """Map an already-proven passing execution to conservative predicates."""
    command = command or ""
    output = output or ""
    observed = f"{command}\n{output}"
    lexical = matching_obligation_ids(contract, command, output)
    full_suite = is_full_repository_suite(command)
    executable = bool(_EXECUTABLE_RE.search(command))
    receipts: list[PredicateReceipt] = []
    for item in contract.obligations:
        predicate = predicates.get(item.obligation_id)
        if predicate is None:
            continue
        verified = False
        if predicate.kind == "behavior":
            verified = full_suite or (
                executable and item.obligation_id in lexical
            )
        elif predicate.kind == "artifact":
            verified = bool(
                executable
                and predicate.scope
                and all(path in observed for path in predicate.scope)
                and re.search(r"(?i)(?:test\s+-[ef]|exists|stat|ls)", command)
            )
        elif predicate.kind == "numeric_threshold":
            numbers = tuple(_NUMBER_RE.findall(str(item.text or "")))
            compact = observed.replace(" ", "")
            verified = bool(
                executable
                and item.obligation_id in lexical
                and numbers
                and all(number.replace(" ", "") in compact for number in numbers)
            )
        elif predicate.kind == "content_scope":
            complete_scope = bool(
                re.search(
                    r"(?i)(?:\brg\b|\bgrep\b|\bfind\b).*(?:\s\.|\s\./)",
                    command,
                )
                and not _SCOPE_EXCLUSION_RE.search(command)
            )
            verified = bool(
                complete_scope
                and executable
                and item.obligation_id in lexical
            )
        if not verified:
            continue
        receipts.append(
            PredicateReceipt(
                predicate_id=predicate.predicate_id,
                obligation_id=predicate.obligation_id,
                kind=predicate.kind,
                outcome="pass",
                command_sha256=hashlib.sha256(
                    command.encode("utf-8", "surrogatepass")
                ).hexdigest(),
                output_sha256=hashlib.sha256(
                    output.encode("utf-8", "surrogatepass")
                ).hexdigest(),
                action_index=action_index,
            )
        )
    return tuple(receipts)
