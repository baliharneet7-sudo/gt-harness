"""Typed, conservative pre-execution action contract for the central engine."""

from __future__ import annotations

import hashlib
import posixpath
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
class ReadSpan:
    """A mechanically observed source range requested by one shell segment."""

    path: str
    start_line: int | None = None
    end_line: int | None = None
    whole_file: bool = False


@dataclass(frozen=True, slots=True)
class ObservedOperation:
    """One mechanically classified operation inside a proposed Bash action.

    This is shell structure, not inferred model intent.  Compound actions can
    carry several operations while unsupported segments remain OTHER.
    """

    segment_index: int
    executable: str
    operation: ActionOperation
    targets: tuple[ActionTarget, ...] = ()
    read_spans: tuple[ReadSpan, ...] = ()
    mutates_workspace: bool = False
    confidence: float = 0.0
    parser_evidence: tuple[str, ...] = ()


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
    operations: tuple[ObservedOperation, ...] = ()
    target_must_be_absent: bool = False
    shell_segments: tuple[tuple[str, ...], ...] = ()
    parser_evidence: tuple[str, ...] = ()

    @property
    def cycle_id(self) -> str:
        return f"call-{self.model_call}:batch-{self.batch_index}:{self.action_id}"

    def as_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["operation"] = self.operation.value
        for operation in row["operations"]:
            operation["operation"] = str(operation["operation"])
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


_SUBMIT_MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
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


def _strip_shell_comments(command: str) -> str:
    """Remove top-level shell comments while preserving command newlines.

    ``shlex`` normally consumes the newline that terminates a comment.  That
    would merge the next command into the current segment, so comments are
    removed before lexing and their newline is retained as a real list
    separator.  Quoted ``#`` characters are ordinary data.
    """

    kept: list[str] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            if char != "\n":
                kept.extend(("\\", char))
            escaped = False
            index += 1
            continue
        if char == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if quote:
            kept.append(char)
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            kept.append(char)
            index += 1
            continue
        if char == "#" and (index == 0 or command[index - 1].isspace()):
            newline = command.find("\n", index)
            if newline < 0:
                break
            kept.append("\n")
            index = newline + 1
            continue
        kept.append(char)
        index += 1
    if escaped:
        kept.append("\\")
    return "".join(kept)


def _shell_parts(
    command: str,
) -> tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]:
    """Parse executable segments and the connectors between them once."""

    try:
        lexer = shlex.shlex(
            _strip_shell_comments(_without_heredoc_bodies(command)),
            posix=True,
            punctuation_chars=";|&<>\n",
        )
        # Newlines are Bash list separators, not generic whitespace.  Keeping
        # them as punctuation prevents two commands from being fused.
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return (), ()
    segments: list[tuple[str, ...]] = []
    connectors: list[str] = []
    current: list[str] = []
    for token in tokens:
        normalized_connector = token.replace("\n", ";")
        if normalized_connector and set(normalized_connector) <= {";", "|", "&"}:
            if current:
                segments.append(tuple(current))
                current = []
                connectors.append(normalized_connector)
            continue
        current.append(token)
    if current:
        segments.append(tuple(current))
    return tuple(segments), tuple(connectors)


def shell_segments(command: str) -> tuple[tuple[str, ...], ...]:
    """Parse top-level executable segments once for proposal and validation."""

    return _shell_parts(command)[0]


def shell_structure(
    command: str,
) -> tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]:
    """Return parsed shell segments and list/pipeline connectors.

    Connectors may contain one terminal operator (notably ``&``) after the
    last segment.  Consumers must therefore not assume ``len(connectors)`` is
    exactly ``len(segments) - 1``.
    """

    return _shell_parts(command)


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


_READ_EXECUTABLES = frozenset(
    {
        "cat",
        "cmp",
        "diff",
        "du",
        "file",
        "head",
        "less",
        "ls",
        "more",
        "nl",
        "od",
        "pwd",
        "readlink",
        "realpath",
        "stat",
        "strings",
        "tail",
        "wc",
        "xxd",
        "hexdump",
    }
)
_SEARCH_EXECUTABLES = frozenset({"rg", "grep", "find", "ack", "ag"})
_VALIDATE_EXECUTABLES = frozenset({"pytest", "ctest"})
_NON_TARGET_TOKENS = frozenset({"/dev/null", "-", "."})
_SED_RANGE = re.compile(r"^(\d+)(?:,(\d+))?p$")


def _resolve_segment_path(value: str, cwd: str) -> str:
    cleaned = value.strip("'\"").replace("\\", "/")
    if not cleaned or cleaned in _NON_TARGET_TOKENS:
        return ""
    if cleaned.startswith("/"):
        return posixpath.normpath(cleaned)
    if cwd:
        return posixpath.normpath(posixpath.join(cwd, cleaned))
    return posixpath.normpath(cleaned)


def _looks_like_path(value: str) -> bool:
    cleaned = value.strip("'\"")
    if not cleaned or cleaned.startswith("-") or cleaned in _NON_TARGET_TOKENS:
        return False
    # Code strings, diagnostics, and shell expressions are not path operands.
    # Abstaining here is safer than presenting source text as a concrete file.
    if any(char.isspace() for char in cleaned):
        return False
    if any(char in cleaned for char in ";|&<>(){}[]=,"):
        return False
    if cleaned.isdigit() or _SED_RANGE.match(cleaned):
        return False
    return bool("/" in cleaned or "." in posixpath.basename(cleaned))


def _segment_operand_paths(words: tuple[str, ...], cwd: str) -> tuple[str, ...]:
    values: list[str] = []
    skip_next = False
    head = words[0].rsplit("/", 1)[-1] if words else ""
    program_indices: set[int] = set()
    opaque_indices: set[int] = set()
    if head in {"python", "python3", "py", "node", "ruby", "perl", "bash", "sh"}:
        for index, token in enumerate(words[1:], start=1):
            if token in {"-c", "-e"} and index + 1 < len(words):
                opaque_indices.add(index + 1)
    if head in {"sed", "awk", "perl", "rg", "grep", "ack", "ag"}:
        expression_option = False
        for index, token in enumerate(words[1:], start=1):
            if expression_option:
                program_indices.add(index)
                expression_option = False
                break
            if token in {"-e", "--expression"}:
                expression_option = True
                continue
            if token.startswith("-"):
                continue
            program_indices.add(index)
            break
    for index, token in enumerate(words[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        if token in {">", ">>"}:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        if index in program_indices:
            continue
        if index in opaque_indices:
            continue
        # A sed program or search query is not a path merely because it
        # contains punctuation.
        if index == 1 and head in {"sed", "awk", "rg", "grep", "ack", "ag"}:
            if _SED_RANGE.match(token.strip("'\"")) or not _looks_like_path(token):
                continue
        if not _looks_like_path(token):
            continue
        resolved = _resolve_segment_path(token, cwd)
        if resolved and resolved not in values:
            values.append(resolved)
    return tuple(values)


def _redirection_targets(words: tuple[str, ...], cwd: str) -> tuple[str, ...]:
    targets: list[str] = []
    for index, token in enumerate(words[:-1]):
        if token not in {">", ">>"}:
            continue
        resolved = _resolve_segment_path(words[index + 1], cwd)
        if resolved and resolved not in targets and resolved != "/dev/null":
            targets.append(resolved)
    return tuple(targets)


def _sed_range(words: tuple[str, ...]) -> tuple[int | None, int | None]:
    for token in words[1:]:
        match = _SED_RANGE.match(token.strip("'\""))
        if match:
            start = int(match.group(1))
            return start, int(match.group(2) or start)
    return None, None


def _segment_is_validation(words: tuple[str, ...], validation: Any | None) -> bool:
    """Bind a whole-command validation result only to its actual runner.

    The immutable classifier is authoritative for the action, but a compound
    command can also contain setup and reporting segments.  Those segments do
    not become validation merely because a later runner is a declared check.
    """

    if not words:
        return False
    head = words[0].rsplit("/", 1)[-1].lower()
    lowered = tuple(word.lower() for word in words[1:])
    if head in {"python", "python3", "py"}:
        if any(word in {"pytest", "unittest"} for word in lowered):
            return True
        script = next((word for word in lowered if not word.startswith("-")), "")
        return any(marker in posixpath.basename(script) for marker in ("test", "check", "verify"))
    if head in {"node", "ruby", "bash", "sh"}:
        script = next((word for word in lowered if not word.startswith("-")), "")
        return any(marker in posixpath.basename(script) for marker in ("test", "check", "verify"))
    if head in {"npm", "pnpm", "yarn", "npx", "gradle", "gradlew", "mvn"}:
        return any(word in {"test", "check", "verify"} for word in lowered)
    return any(marker in head for marker in ("test", "check", "verify"))


def _classify_operations(
    command: str,
    segments: tuple[tuple[str, ...], ...],
    *,
    connectors: tuple[str, ...] = (),
    validation: Any | None,
) -> tuple[ObservedOperation, ...]:
    operations: list[ObservedOperation] = []
    current_cwd = ""
    pending_pipeline_read_indices: list[int] = []
    for segment_index, words in enumerate(segments):
        if not words:
            continue
        if segment_index and (
            segment_index - 1 >= len(connectors)
            or connectors[segment_index - 1] != "|"
        ):
            pending_pipeline_read_indices.clear()
        head = words[0].rsplit("/", 1)[-1].lower()
        if head == "cd" and len(words) > 1:
            current_cwd = _resolve_segment_path(words[1], current_cwd)
            operations.append(
                ObservedOperation(
                    segment_index,
                    head,
                    ActionOperation.OTHER,
                    confidence=1.0,
                    parser_evidence=("shell_context:cwd", f"cwd:{current_cwd}"),
                )
            )
            continue

        operands = _segment_operand_paths(words, current_cwd)
        redirections = _redirection_targets(words, current_cwd)
        base_targets = tuple(ActionTarget(path) for path in operands)
        evidence = (f"head:{head or 'unknown'}", f"segment:{segment_index}")

        if redirections:
            source_operands = tuple(path for path in operands if path not in redirections)
            if head in _READ_EXECUTABLES and source_operands:
                spans = tuple(ReadSpan(path=path, whole_file=True) for path in source_operands)
                operations.append(
                    ObservedOperation(
                        segment_index,
                        head,
                        ActionOperation.READ,
                        tuple(ActionTarget(path) for path in source_operands),
                        spans,
                        confidence=0.98,
                        parser_evidence=(*evidence, "source_before_redirection"),
                    )
                )
            operations.append(
                ObservedOperation(
                    segment_index,
                    head,
                    ActionOperation.EDIT,
                    tuple(ActionTarget(path, "redirection") for path in redirections),
                    mutates_workspace=True,
                    confidence=0.98,
                    parser_evidence=(*evidence, "shell_redirection"),
                )
            )
            pending_pipeline_read_indices.clear()
            continue

        if _SUBMIT_MARKER in command and _SUBMIT_MARKER in " ".join(words):
            operation, confidence = ActionOperation.SUBMIT, 1.0
        elif head in _READ_EXECUTABLES:
            operation, confidence = ActionOperation.READ, 0.98
        elif head == "sed" and "-n" in words and "-i" not in words:
            operation, confidence = ActionOperation.READ, 0.95
        elif head == "awk" and not redirections:
            operation, confidence = ActionOperation.READ, 0.85
        elif head in _SEARCH_EXECUTABLES:
            operation, confidence = ActionOperation.SEARCH, 0.95
        elif head in _VALIDATE_EXECUTABLES or (
            head in {"go", "cargo"} and len(words) > 1 and words[1] == "test"
        ):
            operation, confidence = ActionOperation.VALIDATE, 0.95
        elif _segment_is_validation(words, validation):
            operation, confidence = ActionOperation.VALIDATE, 1.0
        elif head in {"sed", "perl"} and any(flag in words for flag in ("-i", "-pi")):
            operation, confidence = ActionOperation.EDIT, 0.9
        elif head in {
            "apply_patch",
            "cp",
            "install",
            "ln",
            "mv",
            "patch",
            "tee",
            "truncate",
        }:
            operation, confidence = ActionOperation.EDIT, 0.95
        elif head == "git" and len(words) > 1 and words[1] in _MUTATING_GIT_SUBCOMMANDS:
            operation, confidence = ActionOperation.EDIT, 0.9
        elif head in {"touch", "mkdir"}:
            operation, confidence = ActionOperation.CREATE, 0.95
        elif head in {"rm", "rmdir"}:
            operation, confidence = ActionOperation.DELETE, 0.95
        elif head in {"pip", "pip3", "npm", "yarn", "pnpm", "apt", "apt-get"} and any(
            word in {"install", "add"} for word in words[1:3]
        ):
            operation, confidence = ActionOperation.INSTALL, 0.95
        else:
            operation, confidence = ActionOperation.OTHER, 0.2

        read_spans: tuple[ReadSpan, ...] = ()
        if operation == ActionOperation.READ and operands:
            start, end = _sed_range(words) if head == "sed" else (None, None)
            read_spans = tuple(
                ReadSpan(
                    path=path,
                    start_line=start,
                    end_line=end,
                    whole_file=start is None and end is None,
                )
                for path in operands
            )
        mutates = operation in {
            ActionOperation.EDIT,
            ActionOperation.CREATE,
            ActionOperation.DELETE,
            ActionOperation.INSTALL,
        }
        operations.append(
            ObservedOperation(
                segment_index,
                head,
                operation,
                base_targets,
                read_spans,
                mutates,
                confidence,
                evidence,
            )
        )
        current_index = len(operations) - 1
        if operation == ActionOperation.READ and read_spans:
            pending_pipeline_read_indices.append(current_index)
        elif head == "sed" and operation == ActionOperation.READ and not operands:
            start, end = _sed_range(words)
            if start is not None and pending_pipeline_read_indices:
                for read_index in pending_pipeline_read_indices:
                    previous = operations[read_index]
                    operations[read_index] = ObservedOperation(
                        previous.segment_index,
                        previous.executable,
                        previous.operation,
                        previous.targets,
                        tuple(
                            ReadSpan(span.path, start, end, False)
                            for span in previous.read_spans
                        ),
                        previous.mutates_workspace,
                        previous.confidence,
                        (*previous.parser_evidence, "range_from_pipeline_filter"),
                    )
        else:
            pending_pipeline_read_indices.clear()
    return tuple(operations)


_PRIMARY_OPERATION_PRIORITY = {
    ActionOperation.SUBMIT: 0,
    ActionOperation.DELETE: 1,
    ActionOperation.EDIT: 2,
    ActionOperation.CREATE: 3,
    ActionOperation.INSTALL: 4,
    ActionOperation.VALIDATE: 5,
    ActionOperation.SEARCH: 6,
    ActionOperation.READ: 7,
    ActionOperation.OTHER: 8,
}


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
    segments, connectors = _shell_parts(stripped)
    words = list(segments[0]) if len(segments) == 1 else []
    head = words[0].rsplit("/", 1)[-1] if words else ""
    mutation_signals = _mutation_signals(segments)
    operations = _classify_operations(
        command,
        segments,
        connectors=connectors,
        validation=validation,
    )
    meaningful = tuple(item for item in operations if item.operation != ActionOperation.OTHER)
    primary = min(
        meaningful or operations,
        key=lambda item: (_PRIMARY_OPERATION_PRIORITY[item.operation], item.segment_index),
        default=None,
    )
    operation = primary.operation if primary is not None else ActionOperation.OTHER
    confidence = primary.confidence if primary is not None else (0.2 if stripped else 0.0)
    validation_kind: str | None = None
    if validation is not None and bool(getattr(validation, "is_validation", False)):
        validation_kind = str(getattr(validation, "command_class", "validation"))
    elif operation == ActionOperation.VALIDATE:
        validation_kind = head
    # Targets come only from mechanically parsed executable operands and
    # redirections.  Regex-scanning the raw command leaks heredoc bodies,
    # interpreter source strings, and diagnostics into typed intent.
    parsed_targets: list[ActionTarget] = []
    for observed in operations:
        for target in observed.targets:
            if target not in parsed_targets:
                parsed_targets.append(target)
    return ProposedAction(
        action_id=action_id,
        raw_command=command,
        operation=operation,
        targets=tuple(parsed_targets),
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
        operations=operations,
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
