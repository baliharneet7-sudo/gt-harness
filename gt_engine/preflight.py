"""Typed, conservative pre-execution action contract for the central engine."""

from __future__ import annotations

import hashlib
import re
import shlex
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ActionOperation(StrEnum):
    READ = "read"
    SEARCH = "search"
    EDIT = "edit"
    CREATE = "create"
    DELETE = "delete"
    VALIDATE = "validate"
    SUBMIT = "submit"
    INSTALL = "install"
    OTHER = "other"


class ActionDisposition(StrEnum):
    PASS = "pass"
    AUGMENT = "augment"
    RETURN_TO_MODEL = "return_to_model"
    REWRITE = "rewrite"
    SUPPRESS = "suppress"


class PreflightMode(StrEnum):
    """Host policy for a candidate preflight decision.

    OFF preserves the old dispatch path.  SHADOW evaluates and records but
    cannot alter execution.  ASSISTIVE_SAFE may return grounded evidence for
    fresh model reasoning, but cannot rewrite or suppress shell commands.
    """

    OFF = "off"
    SHADOW = "shadow"
    ASSISTIVE_SAFE = "assistive_safe"

    @classmethod
    def parse(cls, value: str | PreflightMode) -> PreflightMode:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            choices = ", ".join(item.value for item in cls)
            raise ValueError(f"unknown preflight mode {value!r}; expected {choices}") from exc


class EvidenceGrade(StrEnum):
    DIRECT = "direct"
    STRUCTURAL = "structural"
    DERIVED = "derived"
    HEURISTIC = "heuristic"


@dataclass(frozen=True, slots=True)
class ActionTarget:
    path: str
    role: str = "operand"


@dataclass(frozen=True, slots=True)
class ProposedAction:
    action_id: str
    raw_command: str
    operation: ActionOperation
    targets: tuple[ActionTarget, ...]
    mutates_workspace: bool
    validation_kind: str | None
    source_revision: str
    workspace_revision: str
    model_call: int
    batch_index: int
    batch_size: int
    parser_confidence: float
    target_must_be_absent: bool = False
    shell_segments: tuple[tuple[str, ...], ...] = ()
    parser_evidence: tuple[str, ...] = ()

    @property
    def cycle_id(self) -> str:
        return f"call-{self.model_call}:batch-{self.batch_index}:{self.action_id}"

    def as_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["operation"] = self.operation.value
        row["cycle_id"] = self.cycle_id
        return row


@dataclass(frozen=True, slots=True)
class PreflightDecision:
    disposition: ActionDisposition
    command: str
    evidence: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    confidence: float = 0.0
    latency_ms: float = 0.0
    source_revision: str = ""
    evidence_grade: EvidenceGrade = EvidenceGrade.DIRECT
    evidence_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["disposition"] = self.disposition.value
        row["evidence_grade"] = self.evidence_grade.value
        return row


@dataclass(slots=True)
class ActionCycleReceipt:
    """Replayable join across proposal, decision, dispatch, and postflight."""

    proposed: ProposedAction
    mode: PreflightMode
    candidate_decision: PreflightDecision
    applied_disposition: ActionDisposition
    applied_reason_codes: tuple[str, ...]
    dispatch_command: str
    executed: bool = False
    postflight: dict[str, Any] = field(default_factory=dict)
    reconsideration: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.proposed.cycle_id,
            "action_id": self.proposed.action_id,
            "proposed": self.proposed.as_dict(),
            "mode": self.mode.value,
            "candidate_decision": self.candidate_decision.as_dict(),
            "applied_disposition": self.applied_disposition.value,
            "applied_reason_codes": list(self.applied_reason_codes),
            "dispatch_command": self.dispatch_command,
            "executed": self.executed,
            "postflight": dict(self.postflight),
            "reconsideration": dict(self.reconsideration),
        }


_PATH = re.compile(
    r"(?:^|[\s'\"])([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+|"
    r"[A-Za-z0-9_.-]+\.[A-Za-z0-9]+)(?=$|[\s'\":,])"
)
_COMPOUND = re.compile(r"(?:&&|\|\||;|\n|`|\$\()")
_MUTATING_EXECUTABLES = frozenset(
    {
        "apply_patch",
        "cp",
        "install",
        "ln",
        "make",
        "mkdir",
        "mv",
        "ninja",
        "patch",
        "rm",
        "rmdir",
        "tee",
        "touch",
        "truncate",
    }
)
_MUTATING_GIT_SUBCOMMANDS = frozenset(
    {
        "add",
        "am",
        "apply",
        "checkout",
        "cherry-pick",
        "clean",
        "clone",
        "commit",
        "init",
        "merge",
        "mv",
        "rebase",
        "reset",
        "restore",
        "revert",
        "rm",
        "stash",
        "switch",
    }
)


def _without_heredoc_bodies(command: str) -> str:
    kept: list[str] = []
    terminator = ""
    for line in command.splitlines():
        if terminator:
            if line.strip() == terminator:
                terminator = ""
            continue
        kept.append(line)
        match = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
        if match:
            terminator = match.group(1)
    return "\n".join(kept)


def shell_segments(command: str) -> tuple[tuple[str, ...], ...]:
    """Parse top-level executable segments once for proposal and validation."""
    try:
        lexer = shlex.shlex(_without_heredoc_bodies(command), posix=True, punctuation_chars=";|&")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
    except ValueError:
        return ()
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token and set(token) <= {";", "|", "&"}:
            if segments[-1]:
                segments.append([])
            continue
        segments[-1].append(token)
    return tuple(tuple(segment) for segment in segments if segment)


def _mutation_signals(segments: tuple[tuple[str, ...], ...]) -> tuple[str, ...]:
    signals: list[str] = []
    for words in segments:
        if not words:
            continue
        head = words[0].rsplit("/", 1)[-1].lower()
        if head in _MUTATING_EXECUTABLES:
            signals.append(f"executable:{head}")
        if head in {"sed", "perl"} and any(flag in words for flag in ("-i", "-pi")):
            signals.append(f"in_place:{head}")
        if head == "git" and len(words) > 1 and words[1] in _MUTATING_GIT_SUBCOMMANDS:
            signals.append(f"git:{words[1]}")
        if any(token in {">", ">>"} or token.startswith(">>") for token in words):
            signals.append("shell_redirection")
    return tuple(dict.fromkeys(signals))


def _targets(command: str) -> tuple[ActionTarget, ...]:
    return tuple(
        ActionTarget(path=value.replace("\\", "/"))
        for value in dict.fromkeys(_PATH.findall(command))
        if not value.startswith("../") and value not in {"/dev/null"}
    )


def adapt_proposed_action(
    action: Mapping[str, Any],
    *,
    source_revision: str,
    workspace_revision: str,
    model_call: int,
    batch_index: int,
    batch_size: int,
    validation: Any | None = None,
) -> ProposedAction:
    command = str(action.get("command") or "")
    action_id = (
        str(action.get("tool_call_id") or "")
        or "action-"
        + hashlib.sha256(f"{model_call}:{batch_index}:{command}".encode()).hexdigest()[:12]
    )
    stripped = command.strip()
    segments = shell_segments(stripped)
    words = list(segments[0]) if len(segments) == 1 else []
    head = words[0].rsplit("/", 1)[-1] if words else ""
    compound = len(segments) != 1 or bool(_COMPOUND.search(stripped))
    mutation_signals = _mutation_signals(segments)
    operation = ActionOperation.OTHER
    confidence = 0.2 if stripped else 0.0
    validation_kind: str | None = None
    if "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in stripped:
        operation, confidence = ActionOperation.SUBMIT, 1.0
    elif validation is not None and bool(getattr(validation, "is_validation", False)):
        operation, confidence = ActionOperation.VALIDATE, 1.0
        validation_kind = str(getattr(validation, "command_class", "validation"))
    elif not compound and head in {"cat", "head", "tail", "less", "more"}:
        operation, confidence = ActionOperation.READ, 0.98
    elif not compound and head == "sed" and "-n" in words and "-i" not in words:
        operation, confidence = ActionOperation.READ, 0.95
    elif not compound and head in {"rg", "grep", "find", "ack", "ag"}:
        operation, confidence = ActionOperation.SEARCH, 0.95
    elif head in {"pytest", "go", "cargo", "make", "ctest"} and (
        head != "go" or (len(words) > 1 and words[1] == "test")
    ):
        operation, confidence = ActionOperation.VALIDATE, 0.95
        validation_kind = head
    elif head in {"sed", "perl"} and any(flag in words for flag in ("-i", "-pi")):
        operation, confidence = ActionOperation.EDIT, 0.9
    elif head in {"touch", "mkdir"}:
        operation, confidence = ActionOperation.CREATE, 0.95
    elif head in {"rm", "rmdir"}:
        operation, confidence = ActionOperation.DELETE, 0.95
    elif head in {"pip", "pip3", "npm", "yarn", "pnpm", "apt", "apt-get"} and any(
        word in {"install", "add"} for word in words[1:3]
    ):
        operation, confidence = ActionOperation.INSTALL, 0.95
    return ProposedAction(
        action_id=action_id,
        raw_command=command,
        operation=operation,
        targets=_targets(command),
        mutates_workspace=(
            operation
            in {
                ActionOperation.EDIT,
                ActionOperation.CREATE,
                ActionOperation.DELETE,
                ActionOperation.INSTALL,
            }
            or bool(mutation_signals)
        ),
        validation_kind=validation_kind,
        source_revision=source_revision,
        workspace_revision=workspace_revision,
        model_call=max(1, int(model_call)),
        batch_index=max(0, int(batch_index)),
        batch_size=max(1, int(batch_size)),
        parser_confidence=confidence,
        target_must_be_absent=(
            operation == ActionOperation.CREATE
            and head == "mkdir"
            and "-p" not in words
            and "--parents" not in words
        ),
        shell_segments=segments,
        parser_evidence=(
            f"head:{head or 'unknown'}",
            f"segments:{len(segments)}",
            f"operation:{operation.value}",
            *(f"mutation:{item}" for item in mutation_signals),
        ),
    )


def pass_decision(proposed: ProposedAction, *reasons: str) -> PreflightDecision:
    return PreflightDecision(
        ActionDisposition.PASS,
        proposed.raw_command,
        reason_codes=tuple(reasons) or ("default_pass",),
        confidence=proposed.parser_confidence,
        source_revision=proposed.source_revision,
    )


@dataclass(frozen=True, slots=True)
class FeatureLifecyclePlacement:
    feature_id: str
    current_trigger: str
    preflight_operations: tuple[ActionOperation, ...]
    postflight_only: bool
    required_inputs: tuple[str, ...]
    evidence_grade: EvidenceGrade
    decision: str


def _placement(
    feature_id: str,
    trigger: str,
    operations: tuple[ActionOperation, ...],
    inputs: tuple[str, ...],
    grade: EvidenceGrade,
    decision: str,
    *,
    postflight_only: bool = False,
) -> FeatureLifecyclePlacement:
    return FeatureLifecyclePlacement(
        feature_id,
        trigger,
        operations,
        postflight_only,
        inputs,
        grade,
        decision,
    )


PREFLIGHT_FEATURE_PLACEMENT = {
    item.feature_id: item
    for item in (
        _placement(
            "obligations",
            "task_start",
            (ActionOperation.SUBMIT,),
            ("task_contract", "current_obligations"),
            EvidenceGrade.DIRECT,
            "read current contract before submit",
        ),
        _placement(
            "localization",
            "task_start/search_result",
            (ActionOperation.EDIT, ActionOperation.CREATE),
            ("source_bound_graph", "typed_targets"),
            EvidenceGrade.STRUCTURAL,
            "shadow until an exact target contradiction is proven",
        ),
        _placement(
            "GT_LOC_RESLOT",
            "task_start/search_result",
            (ActionOperation.EDIT, ActionOperation.CREATE),
            ("ranked_source_anchors", "typed_targets"),
            EvidenceGrade.STRUCTURAL,
            "shadow ranking; never guess a file",
        ),
        _placement(
            "def_partition",
            "task_start/search_result",
            (ActionOperation.EDIT,),
            ("definition_anchors", "reference_anchors"),
            EvidenceGrade.STRUCTURAL,
            "preflight only with graph-proven partitions",
        ),
        _placement(
            "caller_contract",
            "task_start/file_view/search_result/edit_result",
            (ActionOperation.EDIT,),
            ("directed_caller_edges", "target_symbol"),
            EvidenceGrade.STRUCTURAL,
            "preflight only with directed caller evidence",
        ),
        _placement(
            "newfile_precedent",
            "search_result/edit_result",
            (ActionOperation.CREATE,),
            ("exact_create_target", "source_sibling"),
            EvidenceGrade.STRUCTURAL,
            "return only for exact duplicates; precedents start shadow",
        ),
        _placement(
            "GT_CHANGE_SURFACE",
            "edit_result",
            (),
            ("workspace_diff",),
            EvidenceGrade.DIRECT,
            "requires executed diff",
            postflight_only=True,
        ),
        _placement(
            "signature_delta",
            "edit_result",
            (),
            ("before_contents", "after_contents"),
            EvidenceGrade.DIRECT,
            "requires executed source delta",
            postflight_only=True,
        ),
        _placement(
            "GT_PATCH_DELTA",
            "edit_result",
            (),
            ("workspace_diff", "signature_delta"),
            EvidenceGrade.DERIVED,
            "requires executed patch",
            postflight_only=True,
        ),
        _placement(
            "GT_EDIT_CHECK",
            "edit_result",
            (ActionOperation.EDIT, ActionOperation.VALIDATE),
            ("source_revision", "validation_debt"),
            EvidenceGrade.DERIVED,
            "may select a grounded existing check; no speculative test",
        ),
        _placement(
            "syntax_result",
            "edit_result",
            (),
            ("generated_source", "syntax_command_result"),
            EvidenceGrade.DIRECT,
            "requires generated code and command result",
            postflight_only=True,
        ),
        _placement(
            "covering_red",
            "test_result",
            (),
            ("validation_result", "diagnostic"),
            EvidenceGrade.DIRECT,
            "requires executed validator output",
            postflight_only=True,
        ),
        _placement(
            "GT_HYPOTHESIS",
            "test_result",
            (ActionOperation.VALIDATE,),
            ("unchanged_source_revision", "failure_fingerprint"),
            EvidenceGrade.DERIVED,
            "shadow repeated-failure hypothesis before validation",
        ),
        _placement(
            "recovery",
            "test_result",
            (ActionOperation.VALIDATE,),
            ("failure_history", "concrete_alternative"),
            EvidenceGrade.DIRECT,
            "return only on exact unchanged repeated failure with an alternative",
        ),
        _placement(
            "submit_refusal",
            "test_result/submit",
            (ActionOperation.SUBMIT,),
            ("fresh_grounded_failures",),
            EvidenceGrade.DIRECT,
            "return on a fresh explicit failing check",
        ),
        _placement(
            "GT_SS_SUBMIT_RED",
            "test_result/submit",
            (ActionOperation.SUBMIT,),
            ("fresh_grounded_failures", "source_revision"),
            EvidenceGrade.DIRECT,
            "same submit blocker, no duplicate message",
        ),
        _placement(
            "GT_CERT_DELIVERY",
            "test_result/submit",
            (ActionOperation.SUBMIT,),
            ("current_checks", "source_revision"),
            EvidenceGrade.DIRECT,
            "certificate state remains private unless submission needs it",
        ),
    )
}
