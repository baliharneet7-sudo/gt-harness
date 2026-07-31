"""Executable, conservative verification predicates for task obligations."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from gt_engine.task_contract import (
    TaskContract,
    matching_obligation_ids,
    significant_tokens,
)

_SCALAR = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?"
_NUMBER_RE = re.compile(
    rf"(?<![\w.])(?P<value>{_SCALAR})(?:\s*(?P<unit>ms|s|m|mb|gb|%))?",
    re.IGNORECASE,
)
_DIRECT_BOUND_RE = re.compile(
    rf"(?P<op><=|>=|<|>)\s*(?P<value>{_SCALAR})"
    rf"(?:\s*(?P<unit>ms|s|m|mb|gb|%))?",
    re.IGNORECASE,
)
_WORD_BOUND_RE = re.compile(
    rf"(?P<word>below|under|less\s+than|at\s+most|maximum|max(?:imum)?|"
    rf"above|over|more\s+than|at\s+least|minimum|min(?:imum)?)"
    rf"[^0-9+\-]{{0,48}}(?P<value>{_SCALAR})"
    rf"(?:\s*(?P<unit>ms|s|m|mb|gb|%))?",
    re.IGNORECASE,
)
_NUMERIC_FAILURE_RE = re.compile(
    r"(?i)(?:some\s+checks?\s+failed|overall\s*:\s*.*fail|"
    r"all\s+checks\s+passed\s*:\s*false)"
)
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
    r"(?i)(?:grep\s+-v|--exclude|--exclude-dir|"
    r"--glob\s+[\"']?!|-path\s+\S+\s+-prune)"
)
_CONTENT_SCAN_COMMAND_RE = re.compile(
    r"(?i)(?:^|[;&|]\s*)(?:rg|grep|find)\b"
)
_CONTENT_ABSENCE_RE = re.compile(
    r"(?i)(?:\b0\s+(?:matches|findings|secrets|tokens)\b|"
    r"\bno\s+(?:matches|findings|secrets|sensitive values|tokens)\b|"
    r"\b(?:secrets|sensitive values|tokens)\s+(?:are\s+)?not present\b)"
)
_EXIT_CODE_MARKER_RE = re.compile(r"(?im)^\s*\[exit code \d+\]\s*$")


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
    observed_value: str = ""
    operator: str = ""
    required_value: str = ""
    unit: str = ""


@dataclass(frozen=True)
class _NumericBound:
    value: Decimal
    raw: str
    operator: str
    unit: str = ""


def _decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _word_operator(word: str) -> str:
    low = re.sub(r"\s+", " ", (word or "").strip().lower())
    if low in {
        "below", "under", "less than", "at most", "maximum", "max",
    }:
        return "<="
    return ">="


def _required_numeric_bounds(
    contract: TaskContract,
    obligation_text: str,
) -> tuple[_NumericBound, ...]:
    """Extract actual required bounds, excluding incidental bucket/list numbers."""
    bounds: list[_NumericBound] = []
    for match in _DIRECT_BOUND_RE.finditer(obligation_text or ""):
        value = _decimal(match.group("value"))
        if value is not None:
            bounds.append(_NumericBound(
                value,
                match.group("value"),
                match.group("op"),
                (match.group("unit") or "").lower(),
            ))
    for match in _WORD_BOUND_RE.finditer(obligation_text or ""):
        value = _decimal(match.group("value"))
        if value is not None:
            bounds.append(_NumericBound(
                value,
                match.group("value"),
                _word_operator(match.group("word")),
                (match.group("unit") or "").lower(),
            ))
    if bounds:
        return tuple(dict.fromkeys(bounds))

    # Markdown threshold tables often carry values in one row while a sibling
    # obligation supplies "below the thresholds". That context establishes <=,
    # but a bare number without threshold context is never promoted.
    threshold_context = any(
        re.search(
            r"(?i)\b(?:below|under|at most|maximum|thresholds?|limits?)\b",
            str(item.text or ""),
        )
        for item in contract.obligations
    )
    if not threshold_context:
        return ()
    for match in _NUMBER_RE.finditer(obligation_text or ""):
        value = _decimal(match.group("value"))
        if value is not None:
            bounds.append(_NumericBound(
                value,
                match.group("value"),
                "<=",
                (match.group("unit") or "").lower(),
            ))
    return tuple(dict.fromkeys(bounds))


def _comparison_holds(observed: Decimal, operator: str, required: Decimal) -> bool:
    if operator == "<":
        return observed < required
    if operator == ">":
        return observed > required
    if operator == ">=":
        return observed >= required
    return observed <= required


def _observed_for_bound(
    output: str,
    bound: _NumericBound,
) -> tuple[Decimal, str] | None:
    """Find a measured value paired with this bound on one result line."""
    for line in (output or "").splitlines():
        numbers = list(_NUMBER_RE.finditer(line))
        required_matches = [
            match for match in numbers
            if _decimal(match.group("value")) == bound.value
            and (
                not bound.unit
                or (match.group("unit") or "").lower() == bound.unit
            )
        ]
        if not required_matches:
            continue
        if re.search(r"(?i)\bfail(?:ed)?\b|[✗✘]", line):
            return None
        if not re.search(
            r"(?i)(?:<=|>=|<|>|≤|≥|threshold|target|limit|maximum|minimum|"
            r"below|above|under|over|pass|fail|✓|✗)",
            line,
        ):
            continue
        required_match = required_matches[-1]
        candidates: list[tuple[int, Decimal, str]] = []
        for match in numbers:
            value = _decimal(match.group("value"))
            unit = (match.group("unit") or "").lower()
            if value is None or value == bound.value:
                continue
            if bound.unit and unit != bound.unit:
                continue
            distance = abs(match.start() - required_match.start())
            candidates.append((distance, value, match.group("value")))
        if not candidates:
            continue
        _distance, observed, raw = min(candidates, key=lambda item: item[0])
        return observed, raw
    return None


def _numeric_assertion(
    contract: TaskContract,
    obligation_text: str,
    output: str,
) -> tuple[bool, str, str, str, str]:
    if _NUMERIC_FAILURE_RE.search(output or ""):
        return False, "", "", "", ""
    bounds = _required_numeric_bounds(contract, obligation_text)
    if not bounds:
        return False, "", "", "", ""
    witnessed: list[tuple[_NumericBound, Decimal, str]] = []
    for bound in bounds:
        observed = _observed_for_bound(output, bound)
        if observed is None:
            return False, "", "", "", ""
        value, raw = observed
        if not _comparison_holds(value, bound.operator, bound.value):
            return False, raw, bound.operator, bound.raw, bound.unit
        witnessed.append((bound, value, raw))
    bound, _value, raw = witnessed[0]
    return True, raw, bound.operator, bound.raw, bound.unit


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


def is_complete_content_absence_observation(
    command: str,
    output: str,
    returncode: int | None,
) -> bool:
    """Recognize an explicit repository-wide negative content search."""
    command = command or ""
    output = output or ""
    complete_scope = bool(
        _CONTENT_SCAN_COMMAND_RE.search(command)
        and re.search(r"(?:^|\s)(?:\.|\./)(?:\s|$)", command)
        and not _SCOPE_EXCLUSION_RE.search(command)
    )
    if not complete_scope:
        return False
    # rg/grep use status 1 for a successful search with no matches.
    substantive_output = _EXIT_CODE_MARKER_RE.sub("", output).strip()
    empty_negative = returncode == 1 and not substantive_output
    return empty_negative or bool(_CONTENT_ABSENCE_RE.search(output))


def evaluate_passing_observation(
    contract: TaskContract,
    predicates: dict[str, ObligationPredicate],
    command: str,
    output: str,
    *,
    action_index: int,
    returncode: int | None = 0,
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
        observed_value = ""
        operator = ""
        required_value = ""
        unit = ""
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
            (
                verified,
                observed_value,
                operator,
                required_value,
                unit,
            ) = _numeric_assertion(
                contract,
                str(item.text or ""),
                output,
            )
            verified = bool(
                executable and item.obligation_id in lexical and verified
            )
        elif predicate.kind == "content_scope":
            verified = bool(
                is_complete_content_absence_observation(
                    command, output, returncode
                )
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
                observed_value=observed_value,
                operator=operator,
                required_value=required_value,
                unit=unit,
            )
        )
    return tuple(receipts)
