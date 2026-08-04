"""Private state and policy for the host-owned coding-agent runtime.

Nothing in this module is installed in the task container.  The model sees the
stock Mini-SWE Bash interface; this module observes transitions through
Harbor's host-side ``BaseEnvironment`` boundary.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import re
import shlex
import time
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from gt_engine.central_controls import (
    FeatureEffect,
    consumer_spec_for,
)

_MANIFEST_COMMAND = (
    "set -o pipefail; LC_ALL=C find . -xdev -mindepth 1 "
    "-printf '%y\\t%s\\t%T@\\t%C@\\t%P\\t%l\\n' 2>/dev/null "
    "| LC_ALL=C sort | head -n 50001"
)
_PRIVATE_TERMS = re.compile(r"groundtruth|gt_[a-z0-9_]*", re.IGNORECASE)
_MISSING_EXECUTABLE = re.compile(
    r"(?:command not found|not found|no such file or directory|cannot execute)", re.IGNORECASE
)
_FAILURE_LINE = re.compile(r"\b(?:fail(?:ed|ure)?|error|exception|traceback|red)\b", re.I)
_SUBMIT_MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
_MODEL_ACTIONABLE_FEATURES = frozenset(
    {
        "covering_red", "newfile_precedent", "recovery", "signature_delta",
        "submit_refusal", "syntax_result",
    }
)
_NON_MATERIAL_PATH_PARTS = frozenset(
    {"__pycache__", ".pytest_cache", ".mypy_cache", ".git", ".hg", ".svn"}
)
_DERIVED_SUFFIXES = frozenset(
    {
        ".o", ".so", ".a", ".pyc", ".pyo", ".pyd", ".class", ".exe", ".dll",
        ".lib", ".obj", ".elf", ".out", ".bin", ".log", ".dylib", ".jar",
        ".whl", ".tar", ".gz", ".zip",
    }
)
_DERIVED_PATH_PARTS = frozenset(
    {
        "__pycache__", ".pytest_cache", ".mypy_cache", ".hypothesis",
        ".ruff_cache", ".git", ".hg", ".svn", "node_modules", ".venv", "venv",
        "build", "dist", "target", ".tox", "eggs",
    }
)
_BACKGROUND_ARTIFACT_NAMES = frozenset(
    {"benchmark_out.txt", "callback-test.txt", "a.out", "data.comp"}
)
_DELIVERABLE_SUFFIXES = (".jsonl", ".json", ".csv", ".txt", ".md", ".out", ".comp")
_SOURCE_CAPTURE_SUFFIXES = frozenset(
    {
        ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".java",
        ".go", ".rs", ".rb", ".php", ".c", ".h", ".cc", ".cpp", ".hpp",
        ".cs", ".sh", ".bash", ".cob", ".cbl", ".scm", ".ss", ".rkt",
    }
)
_MAX_SOURCE_CAPTURE_BYTES = 250_000


@dataclass(frozen=True, slots=True)
class FileState:
    kind: str
    size: int
    mtime: str
    ctime: str
    link_target: str
    digest: str = ""
    content: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    revision: str
    entries: dict[str, FileState]
    healthy: bool
    reason: str = ""
    elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class WorkspaceTransition:
    action_id: int
    command: str
    before_revision: str
    after_revision: str
    created: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    sensor_healthy: bool = True
    before_contents: dict[str, str] = field(default_factory=dict)
    after_contents: dict[str, str] = field(default_factory=dict)

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return tuple(sorted((*self.created, *self.modified, *self.deleted)))


class ChangeOrigin(StrEnum):
    """Why a path changed.  Only MODEL_AUTHORED advances source revision."""

    MODEL_AUTHORED = "model_authored"
    VALIDATOR_DERIVED = "validator_derived"
    BACKGROUND_DERIVED = "background_derived"
    TASK_DELIVERABLE = "task_deliverable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ClassifiedChange:
    path: str
    kind: str
    origin: ChangeOrigin
    validation_relevant: bool


@dataclass(frozen=True, slots=True)
class RevisionState:
    """Workspace revision (raw audit) versus validation-relevant source state."""

    workspace_revision: str
    source_revision: str
    source_epoch: int = 0


def classify_change(
    path: str,
    *,
    kind: str = "f",
    task_deliverables: Iterable[str] = (),
) -> ClassifiedChange:
    """Classify one changed path against the source-revision model.

    Directories, caches, compiled objects, binaries, build products, logs,
    benchmark output, and background-process writes never advance source
    revision.  Task deliverables are tracked separately and satisfy
    obligations without pretending to be source edits.
    """
    if path in set(task_deliverables):
        return ClassifiedChange(path, kind, ChangeOrigin.TASK_DELIVERABLE, False)
    parts = path.replace("\\", "/").split("/")
    if kind != "f" or any(part in _DERIVED_PATH_PARTS for part in parts):
        return ClassifiedChange(path, kind, ChangeOrigin.BACKGROUND_DERIVED, False)
    lower = path.lower()
    if any(lower.endswith(suffix) for suffix in _DERIVED_SUFFIXES):
        return ClassifiedChange(path, kind, ChangeOrigin.VALIDATOR_DERIVED, False)
    if any(name in path for name in _BACKGROUND_ARTIFACT_NAMES):
        return ClassifiedChange(path, kind, ChangeOrigin.BACKGROUND_DERIVED, False)
    return ClassifiedChange(path, kind, ChangeOrigin.MODEL_AUTHORED, True)


def source_revision_of(
    snapshot: WorkspaceSnapshot,
    task_deliverables: Iterable[str] = (),
) -> str:
    """Hash only validation-relevant regular source files, never artifacts."""
    deliverables = set(task_deliverables)
    digest = hashlib.sha256()
    for path, item in sorted(snapshot.entries.items()):
        if item.kind != "f":
            continue
        if not classify_change(
            path, kind=item.kind, task_deliverables=deliverables
        ).validation_relevant:
            continue
        digest.update(path.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(
            "\t".join(
                (
                    item.kind,
                    str(item.size),
                    item.mtime,
                    item.ctime,
                    item.link_target,
                    item.digest,
                )
            ).encode("utf-8", "surrogateescape")
        )
        digest.update(b"\0")
    return digest.hexdigest()


def task_deliverable_paths(instruction: str) -> tuple[str, ...]:
    """Return paths the task contract explicitly names as required output."""
    found: list[str] = []
    for line in instruction.splitlines():
        if not re.search(
            r"\b(?:output|report|result|write|create|save|produce|generate|deliverable)\b",
            line,
            re.I,
        ):
            continue
        for token in re.findall(r"`([^`\r\n]+)`", line):
            path = token.strip()
            if (
                path.lower().endswith(_DELIVERABLE_SUFFIXES)
                and not is_submit_command(path)
            ):
                found.append(path)
        for match in re.finditer(
            r"(?<![A-Za-z0-9_.-])([\w./-]+\.(?:jsonl?|csv|txt|md|out|comp))\b",
            line,
            re.I,
        ):
            path = match.group(1)
            if path not in found:
                found.append(path)
    return tuple(dict.fromkeys(found))


class InterventionDecision(StrEnum):
    PASS = "PASS"
    ADVISE = "ADVISE"
    HOLD_ONCE = "HOLD_ONCE"
    SHADOW = "SHADOW"


@dataclass(frozen=True, slots=True)
class SubmitDecision:
    decision: InterventionDecision
    blockers: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True, slots=True)
class CheckEvidence:
    command: str
    returncode: int
    revision: str
    grounded: bool
    command_class: str = ""
    failure_kind: str = ""
    source_revision: str = ""


# The historical direct inventory is 10 FACT identities plus 7 CAP_OWNER
# identities.  Keep the inventory in the host-owned runtime as data, rather
# than claiming that a legacy import or an environment flag is an active
# implementation.  A feature is only reported as delivered after its
# boundary-specific trigger is observed.
CENTRAL_FEATURES: tuple[dict[str, str], ...] = (
    {"id": "caller_contract", "kind": "FACT", "owner": "contract_map"},
    {"id": "covering_red", "kind": "FACT", "owner": "covering_runner"},
    {"id": "def_partition", "kind": "FACT", "owner": "post_search"},
    {"id": "localization", "kind": "FACT", "owner": "v1r_brief"},
    {"id": "newfile_precedent", "kind": "FACT", "owner": "change_surface"},
    {"id": "obligations", "kind": "FACT", "owner": "spec"},
    {"id": "recovery", "kind": "FACT", "owner": "governor"},
    {"id": "signature_delta", "kind": "FACT", "owner": "patch_delta"},
    {"id": "submit_refusal", "kind": "FACT", "owner": "submit_gate"},
    {"id": "syntax_result", "kind": "FACT", "owner": "edit_check"},
    {"id": "GT_CERT_DELIVERY", "kind": "CAP", "owner": "submit_refusal"},
    {"id": "GT_CHANGE_SURFACE", "kind": "CAP", "owner": "newfile_precedent"},
    {"id": "GT_EDIT_CHECK", "kind": "CAP", "owner": "syntax_result"},
    {"id": "GT_HYPOTHESIS", "kind": "CAP", "owner": "recovery"},
    {"id": "GT_LOC_RESLOT", "kind": "CAP", "owner": "localization"},
    {"id": "GT_PATCH_DELTA", "kind": "CAP", "owner": "signature_delta"},
    {"id": "GT_SS_SUBMIT_RED", "kind": "CAP", "owner": "submit_refusal"},
)
CENTRAL_FEATURE_IDS = tuple(item["id"] for item in CENTRAL_FEATURES)
CENTRAL_CAP_OWNERS = {
    item["id"]: item["owner"] for item in CENTRAL_FEATURES if item["kind"] == "CAP"
}
CENTRAL_FEATURE_BOUNDARIES = {
    "caller_contract": ("file_view", "search_result", "edit_result"),
    "covering_red": "test_result",
    "def_partition": "search_result",
    "localization": "search_result",
    "newfile_precedent": ("search_result", "edit_result"),
    "obligations": "task_start",
    "recovery": "test_result",
    "signature_delta": "edit_result",
    "submit_refusal": ("test_result", "submit"),
    "syntax_result": "edit_result",
    "GT_CERT_DELIVERY": ("test_result", "submit"),
    "GT_CHANGE_SURFACE": "edit_result",
    "GT_EDIT_CHECK": "edit_result",
    "GT_HYPOTHESIS": "test_result",
    "GT_LOC_RESLOT": "search_result",
    "GT_PATCH_DELTA": "edit_result",
    "GT_SS_SUBMIT_RED": ("test_result", "submit"),
}


def feature_payload_valid(
    feature_id: str,
    payload: dict[str, Any],
    *,
    boundary: str,
    revision: str,
    fresh: bool,
) -> bool:
    """Validate the minimum non-opaque payload contract for one delivery."""
    if feature_id not in CENTRAL_FEATURE_IDS or not revision or not fresh:
        return False
    expected_boundary = CENTRAL_FEATURE_BOUNDARIES[feature_id]
    if boundary not in (
        expected_boundary if isinstance(expected_boundary, tuple) else (expected_boundary,)
    ):
        return False
    if not payload.get("message"):
        return False
    required = {
        "caller_contract": ("callers_verified",),
        "covering_red": (
            "check_failed",
            "command_class",
            "failure_kind",
            "attribution",
        ),
        "def_partition": ("definitions", "references"),
        "localization": ("candidate_locations",),
        "newfile_precedent": (),
        "obligations": ("requirements_present",),
        "recovery": ("repeat_count",),
        "signature_delta": ("signature_edit",),
        "submit_refusal": ("submission_risk", "blockers"),
        "syntax_result": ("ok",),
        "GT_CERT_DELIVERY": ("sensor_healthy", "readiness"),
        "GT_CHANGE_SURFACE": ("owner_feature",),
        "GT_EDIT_CHECK": ("owner_feature",),
        "GT_HYPOTHESIS": ("owner_feature",),
        "GT_LOC_RESLOT": ("owner_feature",),
        "GT_PATCH_DELTA": ("owner_feature",),
        "GT_SS_SUBMIT_RED": ("owner_feature", "blockers"),
    }[feature_id]
    if feature_id == "newfile_precedent":
        return bool(payload.get("precedent_verified") or payload.get("created_files"))
    return all(key in payload for key in required)


# A model-visible payload is grounded only when it names concrete evidence:
# an anchor path, a symbol, a caller, a validator command, a diagnostic, or a
# blocker.  Generic booleans and scope reminders are never grounded and must
# never reach the model as an advisory.  Unlisted features have no grounding
# contract yet and therefore cannot be model-visible.
_GROUNDING_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "localization": ("anchors",),
    "def_partition": ("definition_anchors", "reference_anchors"),
    "caller_contract": ("callers",),
    "newfile_precedent": ("precedent_path",),
    "signature_delta": ("symbol", "before_signature", "after_signature"),
    "covering_red": ("command", "diagnostic", "attribution"),
    "recovery": ("alternate_action",),
    "obligations": ("obligation_ids", "declared_checks"),
    "syntax_result": ("path", "command", "returncode"),
    "submit_refusal": ("blockers",),
    "GT_EDIT_CHECK": ("declared_check", "changed_paths"),
    "GT_LOC_RESLOT": ("selected_anchors",),
}


def feature_payload_grounded(feature_id: str, payload: dict[str, Any]) -> bool:
    """True only when a model-visible payload names concrete evidence."""
    required = _GROUNDING_REQUIREMENTS.get(feature_id)
    if required is None:
        return False
    return all(bool(payload.get(key)) for key in required)


def _snapshot_revision(entries: dict[str, FileState]) -> str:
    digest = hashlib.sha256()
    for path, item in sorted(entries.items()):
        digest.update(path.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(
            "\t".join(
                (
                    item.kind,
                    str(item.size),
                    item.mtime,
                    item.ctime,
                    item.link_target,
                    item.digest,
                )
            ).encode("utf-8", "surrogateescape")
        )
        digest.update(b"\0")
    return digest.hexdigest()


def _same_metadata(left: FileState, right: FileState) -> bool:
    return (
        left.kind,
        left.size,
        left.mtime,
        left.ctime,
        left.link_target,
    ) == (
        right.kind,
        right.size,
        right.mtime,
        right.ctime,
        right.link_target,
    )


def parse_manifest(raw: str, *, elapsed_seconds: float = 0.0) -> WorkspaceSnapshot:
    """Parse the host-only metadata probe emitted by ``find -printf``."""
    entries: dict[str, FileState] = {}
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line:
            continue
        parts = line.split("\t", 5)
        if len(parts) != 6:
            return WorkspaceSnapshot(
                revision="",
                entries={},
                healthy=False,
                reason=f"malformed manifest line {line_number}",
                elapsed_seconds=elapsed_seconds,
            )
        kind, size, mtime, ctime, path, link_target = parts
        try:
            parsed_size = int(size)
        except ValueError:
            return WorkspaceSnapshot(
                revision="",
                entries={},
                healthy=False,
                reason=f"invalid size on manifest line {line_number}",
                elapsed_seconds=elapsed_seconds,
            )
        entries[path] = FileState(kind, parsed_size, mtime, ctime, link_target)
    return WorkspaceSnapshot(
        revision=_snapshot_revision(entries),
        entries=entries,
        healthy=True,
        elapsed_seconds=elapsed_seconds,
    )


def diff_snapshots(
    before: WorkspaceSnapshot,
    after: WorkspaceSnapshot,
    *,
    action_id: int,
    command: str,
) -> WorkspaceTransition:
    before_paths = set(before.entries)
    after_paths = set(after.entries)
    shared = before_paths & after_paths
    changed_paths = (after_paths - before_paths) | (before_paths - after_paths) | {
        path for path in shared if before.entries[path] != after.entries[path]
    }
    return WorkspaceTransition(
        action_id=action_id,
        command=command,
        before_revision=before.revision,
        after_revision=after.revision,
        created=tuple(sorted(after_paths - before_paths)),
        modified=tuple(
            sorted(path for path in shared if before.entries[path] != after.entries[path])
        ),
        deleted=tuple(sorted(before_paths - after_paths)),
        sensor_healthy=before.healthy and after.healthy,
        before_contents={
            path: before.entries[path].content
            for path in sorted(changed_paths & before_paths)
            if before.entries[path].content is not None
        },
        after_contents={
            path: after.entries[path].content
            for path in sorted(changed_paths & after_paths)
            if after.entries[path].content is not None
        },
    )


def normalize_command(command: str) -> str:
    return " ".join(command.strip().split())


def is_submit_command(command: str) -> bool:
    compact = re.sub(r"[\s'\"\\+]", "", command)
    return _SUBMIT_MARKER in compact


@dataclass(frozen=True, slots=True)
class ValidationClassification:
    """Single immutable classification of one shell action's validation meaning.

    The agent classifies each executed action exactly once and shares this
    object with the feature runtime, the evidence ledger, the receipt writer,
    and the metrics extractor so no component ever reparses the command.
    """

    command_class: str
    is_validation: bool
    grounded: bool
    failure_kind: str
    command: str = ""
    normalized_command: str = ""
    declared_check_id: str | None = None
    result_code: int | None = None
    source_revision: str = ""
    workspace_revision: str = ""
    diagnostic_fingerprint: str = ""

    def with_result(
        self,
        *,
        result_code: int,
        output: str,
        source_revision: str,
        workspace_revision: str,
    ) -> ValidationClassification:
        """Return a copy carrying execution outcome and revision bindings."""
        failure_kind = classify_failure_kind(result_code, output)
        failure_signature = " ".join(
            line.strip()
            for line in (output or "").splitlines()
            if _FAILURE_LINE.search(line)
        )[:240]
        fingerprint = hashlib.sha256(
            f"{result_code}\0{failure_signature.lower()}".encode("utf-8", "replace")
        ).hexdigest()[:16]
        return replace(
            self,
            failure_kind=failure_kind,
            result_code=result_code,
            source_revision=source_revision,
            workspace_revision=workspace_revision,
            diagnostic_fingerprint=fingerprint,
        )


def _without_heredoc_bodies(command: str) -> str:
    """Keep shell structure while removing arbitrary program/data bodies."""
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


def _shell_segments(command: str) -> tuple[tuple[str, ...], ...]:
    """Return top-level shell command words, excluding comments and heredocs."""
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


def _recognized_validation(words: tuple[str, ...]) -> bool:
    """Recognize real validator invocations only from executable positions."""
    if not words:
        return False
    index = 0
    while index < len(words) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[index]):
        index += 1
    while index < len(words) and words[index] in {"env", "command", "timeout", "sudo"}:
        wrapper = words[index]
        index += 1
        while index < len(words) and (words[index].startswith("-") or "=" in words[index]):
            option = words[index]
            index += 1
            # These wrappers have a small set of detached option arguments.
            # Consume them so their values cannot be mistaken for an executable.
            if (
                (wrapper == "timeout" and option in {"-k", "-s"})
                or (wrapper == "env" and option in {"-u", "--unset"})
                or (
                    wrapper == "sudo"
                    and option in {"-C", "-D", "-g", "-h", "-p", "-r", "-t", "-u"}
                )
            ) and index < len(words):
                index += 1
        if wrapper == "timeout" and index < len(words):
            # GNU/POSIX timeout syntax places a duration before the command.
            index += 1
    if index >= len(words):
        return False
    executable = words[index].rsplit("/", 1)[-1].lower()
    args = words[index + 1 :]
    if executable in {"pytest", "py.test", "ctest"}:
        return True
    if executable in {"npm", "pnpm", "yarn", "mvn", "gradle", "cargo", "go"}:
        return bool(args and args[0] == "test")
    if executable in {"python", "python3", "python3.12", "python3.11"}:
        if len(args) >= 2 and args[0] == "-m" and args[1] in {"pytest", "unittest"}:
            return True
        script_name = args[0].rsplit("/", 1)[-1] if args else ""
        return bool(
            script_name
            and re.fullmatch(r"(?:test|tests|verify)[A-Za-z0-9_.-]*\.py", script_name, re.I)
        )
    return executable in {"unittest", "test"}


def classify_validation_command(
    command: str, explicit_checks: Iterable[str] = ()
) -> ValidationClassification:
    """Classify validation by shell structure, never by source/comment text."""
    normalized = normalize_command(command)
    grounded = is_grounded_check(normalized, explicit_checks)
    recognized = any(_recognized_validation(segment) for segment in _shell_segments(command))
    if grounded:
        command_class = "declared_validation"
    elif recognized:
        command_class = "recognized_validation"
    else:
        command_class = "exploration_or_unknown"
    return ValidationClassification(
        command_class=command_class,
        is_validation=grounded or recognized,
        grounded=grounded,
        failure_kind="",
        command=command,
        normalized_command=normalized,
        declared_check_id=_declared_check_id(normalized, explicit_checks),
    )


def _declared_check_id(normalized: str, explicit_checks: Iterable[str]) -> str | None:
    for check in explicit_checks:
        if check == normalized or check in normalized:
            return check
    return None


def select_declared_check(
    explicit_checks: Iterable[str],
    states: dict[str, str],
) -> str | None:
    """Pick the highest-priority declared check that is not freshly passing.

    Never blindly selects ``explicit_checks[0]``.  Task verifiers and focused
    behavioral checks outrank generic build steps.  A check whose state is
    ``passed`` is satisfied at the current source revision and skipped; a
    ``stale`` check (source changed after its pass) is a candidate again.
    """
    ordered = list(dict.fromkeys(explicit_checks))
    if not ordered:
        return None

    def priority(check: str) -> int:
        lower = check.lower()
        if "verify" in lower or "/test" in lower:
            return 0
        if "pytest" in lower or "unittest" in lower or "test" in lower:
            return 1
        if "build" in lower or "compile" in lower or "setup.py" in lower:
            return 2
        return 3

    ranked = sorted(enumerate(ordered), key=lambda pair: (priority(pair[1]), pair[0]))
    for _, check in ranked:
        if states.get(check) != "passed":
            return check
    return None


def classify_failure_kind(returncode: int, output: str) -> str:
    if returncode in {126, 127} or _MISSING_EXECUTABLE.search(output or ""):
        return "environment_failure"
    return "validation_failure"


def is_check_command(command: str) -> bool:
    return classify_validation_command(command).is_validation


def explicit_check_commands(instruction: str) -> tuple[str, ...]:
    """Return explicitly named validation commands or verifier artifacts.

    Benchmark instructions frequently name a verifier as ``/app/test_x.py``
    rather than spelling out its interpreter.  The path is still grounded task
    evidence: a later command containing it is a declared validation command.
    """
    checks = []
    for line in instruction.splitlines():
        context_declares_validation = bool(
            re.search(r"\b(?:test|verify|check|validate|compile|build)\b", line, re.I)
        )
        for candidate in re.findall(r"`([^`\r\n]+)`", line):
            if (
                (is_check_command(candidate) or context_declares_validation)
                and not is_submit_command(candidate)
            ):
                checks.append(normalize_command(candidate))
        stripped = line.strip()
        if (
            context_declares_validation
            and "|" in stripped
            and re.match(r"(?:echo|printf)\b", stripped)
            and re.search(r"\b(?:python|python3|node|ruby|bash)\b", stripped)
        ):
            checks.append(normalize_command(stripped))
    for path in re.findall(
        r"(?<![A-Za-z0-9_.-])(/(?:[A-Za-z0-9_.-]+/)*(?:test|tests|verify)[A-Za-z0-9_.-]*)",
        instruction,
        flags=re.IGNORECASE,
    ):
        checks.append(normalize_command(path))
    return tuple(dict.fromkeys(checks))


def is_grounded_check(command: str, explicit_checks: Iterable[str]) -> bool:
    normalized = normalize_command(command)
    return any(check == normalized or check in normalized for check in explicit_checks)


@dataclass(slots=True)
class EvidenceLedger:
    """Fresh deterministic evidence with bounded, fail-open submit holds."""

    max_holds: int = 1
    checks: dict[str, CheckEvidence] = field(default_factory=dict)
    outcomes: dict[str, CheckEvidence] = field(default_factory=dict)
    _holds: dict[tuple[str, tuple[str, ...]], int] = field(default_factory=dict)

    def record_check(
        self,
        command: str,
        *,
        returncode: int,
        revision: str,
        grounded: bool,
        classification: ValidationClassification | None = None,
    ) -> None:
        key = normalize_command(command)
        evidence = CheckEvidence(
            command=key,
            returncode=returncode,
            revision=revision,
            grounded=grounded,
            command_class=(
                classification.command_class if classification else "unknown"
            ),
            failure_kind=(
                classification.failure_kind
                if classification and classification.is_validation
                else ""
            ),
            source_revision=(
                classification.source_revision if classification else revision
            ),
        )
        self.outcomes[key] = evidence
        if returncode == 0:
            self.checks.pop(key, None)
            return
        self.checks[key] = evidence

    def submit_decision(self, revision: str, *, sensor_healthy: bool = True) -> SubmitDecision:
        if not sensor_healthy:
            return SubmitDecision(InterventionDecision.PASS, reason="sensor degraded")
        blockers = tuple(
            sorted(
                item.command
                for item in self.checks.values()
                if item.grounded and item.revision == revision and item.returncode != 0
            )
        )
        if not blockers:
            return SubmitDecision(InterventionDecision.PASS)
        hold_key = (revision, blockers)
        used = self._holds.get(hold_key, 0)
        if used >= self.max_holds:
            return SubmitDecision(
                InterventionDecision.PASS,
                blockers,
                reason="bounded hold exhausted",
            )
        self._holds[hold_key] = used + 1
        return SubmitDecision(
            InterventionDecision.HOLD_ONCE,
            blockers,
            reason="fresh grounded check is failing",
        )

    def readiness_evidence(self, revision: str) -> tuple[CheckEvidence, ...]:
        """Return recognized checks whose results belong to the current revision."""
        return tuple(
            sorted(
                (
                    item
                    for item in self.outcomes.values()
                    if item.grounded and item.revision == revision
                ),
                key=lambda item: item.command,
            )
        )


def render_runtime_feedback(detail: str, *, limit: int = 320) -> str:
    """Render concise model feedback without exposing private implementation names."""
    cleaned = _PRIVATE_TERMS.sub("runtime", " ".join(detail.split()))
    prefix = "Runtime check: "
    suffix = " Submit again to continue without another hold."
    available = max(0, limit - len(prefix) - len(suffix))
    if len(cleaned) > available:
        cleaned = cleaned[: max(0, available - 3)].rstrip() + "..."
    return (prefix + cleaned + suffix)[:limit]


def render_runtime_advisory(detail: str, *, limit: int = 160) -> str:
    """Render ordinary evidence without falsely implying a submit boundary."""
    cleaned = _PRIVATE_TERMS.sub("runtime", " ".join(detail.split()))
    prefix = "Runtime evidence: "
    available = max(0, limit - len(prefix))
    if len(cleaned) > available:
        cleaned = cleaned[: max(0, available - 3)].rstrip() + "..."
    return (prefix + cleaned)[:limit]


class WorkspaceSensor:
    """Ephemeral host-side workspace observer; writes no task-container state."""

    def __init__(
        self,
        *,
        max_entries: int = 50_000,
        max_seconds: float = 2.0,
        max_hashes: int = 100,
        max_hash_bytes: int = 50_000_000,
    ) -> None:
        self.max_entries = max_entries
        self.max_seconds = max_seconds
        self.max_hashes = max_hashes
        self.max_hash_bytes = max_hash_bytes

    @staticmethod
    def _degraded(
        previous: WorkspaceSnapshot | None, reason: str, elapsed: float
    ) -> WorkspaceSnapshot:
        if previous is not None:
            return WorkspaceSnapshot(
                previous.revision,
                previous.entries,
                False,
                reason,
                elapsed,
            )
        return WorkspaceSnapshot("", {}, False, reason, elapsed)

    async def scan(
        self,
        environment: Any,
        *,
        cwd: str,
        previous: WorkspaceSnapshot | None = None,
    ) -> WorkspaceSnapshot:
        started = time.monotonic()
        try:
            result = await environment.exec(
                _MANIFEST_COMMAND,
                cwd=cwd,
                env={},
                timeout_sec=max(1, int(self.max_seconds + 0.999)),
            )
        except Exception as exc:  # task images and transports vary; never block
            return self._degraded(
                previous,
                f"manifest command error: {type(exc).__name__}",
                time.monotonic() - started,
            )
        elapsed = time.monotonic() - started
        if result.return_code != 0:
            return self._degraded(previous, "manifest command failed", elapsed)
        raw = result.stdout or ""
        if raw.count("\n") > self.max_entries:
            return self._degraded(previous, "workspace entry limit exceeded", elapsed)
        snapshot = parse_manifest(raw, elapsed_seconds=elapsed)
        if not snapshot.healthy:
            return self._degraded(previous, snapshot.reason, elapsed)
        if elapsed > self.max_seconds:
            return replace(snapshot, healthy=False, reason="workspace scan time exceeded")
        if previous is not None and not previous.healthy:
            return snapshot

        if previous is None:
            candidates = [
                path
                for path, state in sorted(snapshot.entries.items())
                if state.kind == "f"
                and any(path.lower().endswith(suffix) for suffix in _SOURCE_CAPTURE_SUFFIXES)
                and state.size <= _MAX_SOURCE_CAPTURE_BYTES
            ]
            changed = []
            captured_bytes = 0
            for path in candidates:
                size = snapshot.entries[path].size
                if len(changed) >= self.max_hashes or captured_bytes + size > self.max_hash_bytes:
                    break
                changed.append(path)
                captured_bytes += size
        else:
            changed = [
                path
                for path, state in snapshot.entries.items()
                if state.kind == "f"
                and (
                    previous.entries.get(path) is None
                    or not _same_metadata(previous.entries[path], state)
                )
            ]
        if len(changed) > self.max_hashes:
            return replace(snapshot, healthy=False, reason="changed-file hash limit exceeded")
        if sum(snapshot.entries[path].size for path in changed) > self.max_hash_bytes:
            return replace(snapshot, healthy=False, reason="changed-file byte limit exceeded")
        entries = dict(snapshot.entries)
        if previous is not None:
            for path, state in tuple(entries.items()):
                old = previous.entries.get(path)
                if old is not None and _same_metadata(old, state) and old.digest:
                    entries[path] = replace(
                        state,
                        digest=old.digest,
                        content=old.content,
                    )
        if changed:
            command = "sha256sum -- " + " ".join(shlex.quote(path) for path in changed)
            try:
                hashes = await environment.exec(command, cwd=cwd, env={}, timeout_sec=10)
            except Exception as exc:  # hashing is evidence, never task authority
                return replace(
                    snapshot,
                    healthy=False,
                    reason=f"changed-file hashing error: {type(exc).__name__}",
                )
            lines = (hashes.stdout or "").splitlines()
            if hashes.return_code != 0 or len(lines) != len(changed):
                return replace(snapshot, healthy=False, reason="changed-file hashing failed")
            for path, line in zip(changed, lines, strict=True):
                digest = line.split(maxsplit=1)[0]
                if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                    return replace(snapshot, healthy=False, reason="invalid changed-file hash")
                entries[path] = replace(entries[path], digest=digest.lower())
        capture_paths = [
            path
            for path in changed
            if any(path.lower().endswith(suffix) for suffix in _SOURCE_CAPTURE_SUFFIXES)
            and entries[path].size <= _MAX_SOURCE_CAPTURE_BYTES
        ][:8]
        if capture_paths:
            script = (
                "import base64,json,pathlib,sys;"
                "print(json.dumps({p:base64.b64encode(pathlib.Path(p).read_bytes()).decode()"
                " for p in sys.argv[1:]}))"
            )
            command = "python3 -c " + shlex.quote(script) + " " + " ".join(
                shlex.quote(path) for path in capture_paths
            )
            try:
                captured = await environment.exec(command, cwd=cwd, env={}, timeout_sec=10)
                encoded = json.loads(captured.stdout or "{}") if captured.return_code == 0 else {}
                for path in capture_paths:
                    value = encoded.get(path)
                    if isinstance(value, str):
                        content = base64.b64decode(value).decode("utf-8", "replace")
                        entries[path] = replace(entries[path], content=content)
            except Exception:
                # Content witnesses improve semantic features but metadata and
                # hashes remain authoritative when a task image lacks Python.
                pass
        return replace(snapshot, entries=entries, revision=_snapshot_revision(entries))


def lint_commands(paths: Iterable[str]) -> tuple[tuple[str, str], ...]:
    """Return conservative, no-artifact syntax probes for changed files."""
    commands: list[tuple[str, str]] = []
    for path in sorted(set(paths))[:4]:
        quoted = shlex.quote(path)
        suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if suffix == "py":
            command = (
                "command -v python3 >/dev/null 2>&1 || exit 0; "
                f"PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile -- {quoted}"
            )
        elif suffix in {"js", "mjs", "cjs"}:
            command = f"command -v node >/dev/null 2>&1 || exit 0; node --check -- {quoted}"
        elif suffix in {"sh", "bash"}:
            command = f"command -v bash >/dev/null 2>&1 || exit 0; bash -n -- {quoted}"
        elif suffix == "rb":
            command = f"command -v ruby >/dev/null 2>&1 || exit 0; ruby -c -- {quoted}"
        elif suffix in {"cob", "cbl"}:
            command = f"command -v cobc >/dev/null 2>&1 || exit 0; cobc -fsyntax-only -- {quoted}"
        else:
            continue
        commands.append((path, command))
    return tuple(commands)


@dataclass(frozen=True, slots=True)
class FeatureReceipt:
    """Private, content-minimal proof that one central feature was evaluated."""

    feature_id: str
    kind: str
    boundary: str
    action_id: int
    revision: str
    decision: str
    reason: str
    payload: dict[str, Any]
    fresh: bool
    model_visible: bool
    source_revision: str = ""
    source_epoch: int = 0


@dataclass(slots=True)
class CentralControllerState:
    """Operational state reduced from feature payloads inside Mini-SWE's loop."""

    contract: dict[str, Any] = field(default_factory=dict)
    localization: dict[str, Any] = field(default_factory=dict)
    impact: dict[str, Any] = field(default_factory=dict)
    change_surface: dict[str, Any] = field(default_factory=dict)
    patch_delta: dict[str, Any] = field(default_factory=dict)
    validation_plan: dict[str, Any] = field(default_factory=dict)
    validation_results: dict[str, Any] = field(default_factory=dict)
    failure_state: dict[str, Any] = field(default_factory=dict)
    submission_state: dict[str, Any] = field(default_factory=dict)
    certificate: dict[str, Any] = field(default_factory=dict)
    source_revision: str = ""
    workspace_revision: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": dict(self.contract),
            "localization": dict(self.localization),
            "impact": dict(self.impact),
            "change_surface": dict(self.change_surface),
            "patch_delta": dict(self.patch_delta),
            "validation_plan": dict(self.validation_plan),
            "validation_results": dict(self.validation_results),
            "failure_state": dict(self.failure_state),
            "submission_state": dict(self.submission_state),
            "certificate": dict(self.certificate),
            "source_revision": self.source_revision,
            "workspace_revision": self.workspace_revision,
        }


class CentralFeatureRuntime:
    """Host-side trigger router for the complete 17-feature inventory.

    This deliberately does not scrape task source or inject a second tool. It
    observes only action metadata, command text, return status, and the
    non-Git workspace transition already collected by :class:`WorkspaceSensor`.
    Every feature is enabled by default, but a feature is marked DELIVERED only
    when its conservative trigger is present. CAP rows are emitted with their
    owning FACT, making ownership and delivery auditable without pretending
    that an untriggered feature fired.
    """

    _SEARCH = re.compile(r"(?:^|[;&|\s])(rg|grep|find|ack|ag)(?:\s|$)", re.I)
    _DEFINITION = re.compile(r"\b(?:def|class|function|func|sub|procedure)\b|=>")
    _CALLSITE = re.compile(r"\b(?:caller|callers|call\s*site|references?)\b", re.I)
    _EDIT = re.compile(
        r"(?:apply_patch|sed\s+-i|perl\s+-i|python(?:3)?\s+-c|ruby\s+-i|"
        r"awk\s+.*>|\b(?:touch|tee|cp|mv)\b|>>|\becho\b.*>)",
        re.I,
    )
    _SIGNATURE = re.compile(
        r"\b(?:def|function|func|sub|procedure|class)\s+[A-Za-z_]\w*\s*\(",
        re.I,
    )
    _FAILURE = re.compile(r"\b(?:fail(?:ed|ure)?|error|exception|traceback|red)\b", re.I)
    _PRECEDENT = re.compile(r"\b(?:precedent|sibling|registry|existing|pattern)\b", re.I)

    def __init__(
        self,
        *,
        enabled: bool = True,
        model_visible: bool = False,
        max_guidance_events: int = 4,
        max_guidance_chars: int = 640,
    ) -> None:
        self.enabled = enabled
        self.model_visible = model_visible
        self.receipts: list[FeatureReceipt] = []
        self._seen: set[tuple[str, int, str]] = set()
        self._failed_actions: dict[tuple[str, str, int, str], int] = {}
        self._searched = False
        self._precedent_verified = False
        self._post_edit_checks = 0
        self._feedback_cursor = 0
        self._guidance_events = 0
        self._guidance_chars = 0
        self._guidance_features: list[str] = []
        self._guidance_candidates = 0
        self._guidance_suppressed = 0
        self._guided_keys: set[tuple[str, str, str]] = set()
        self._prepared_guidance: dict[str, Any] | None = None
        self._explicit_checks: tuple[str, ...] = ()
        self.max_guidance_events = max_guidance_events
        self.max_guidance_chars = max_guidance_chars
        self._action_metrics: dict[str, int] = {
            "observed_actions": 0,
            "successful_actions": 0,
            "failed_actions": 0,
            "search_actions": 0,
            "check_actions": 0,
            "workspace_change_actions": 0,
            "no_change_actions": 0,
            "repeated_commands": 0,
            "created_paths": 0,
            "modified_paths": 0,
            "deleted_paths": 0,
            "command_chars": 0,
            "observation_chars": 0,
            "lint_checks": 0,
            "lint_passes": 0,
            "lint_failures": 0,
            "engine_actions": 0,
            "submit_attempts": 0,
            "submit_holds": 0,
            "submit_risks": 0,
            "batch_interrupts": 0,
            "interrupted_actions": 0,
        }
        self._command_counts: dict[str, int] = {}
        self._lifecycle: dict[str, dict[str, Any]] = {}
        self._workspace_edited = False
        self._unvalidated_material_edits = 0
        self._validation_debt_notified = False
        self._consumer_paths: dict[str, list[str]] = {}
        self._effects: list[FeatureEffect] = []
        self._effect_cursor = 0
        self._controller_state = CentralControllerState()
        self._effect_applications: list[dict[str, Any]] = []
        # Additive provenance only.  This trace never participates in routing
        # or policy; it records whether an already-existing consumer path was
        # actually exercised.
        self._effect_trace: list[dict[str, Any]] = []
        self._producer_events: list[dict[str, Any]] = []
        self._batch_interrupts: list[dict[str, Any]] = []
        self._task_deliverables: set[str] = set()
        self._source_epoch = 0
        self._declared_check_states: dict[str, str] = {}
        self._validation_log: list[dict[str, Any]] = []
        self._recent_source_paths: tuple[str, ...] = ()
        self._precedent_path = ""
        self._submit_risk_revisions: set[str] = set()

    def _mark_lifecycle(self, phase: str, *, action_id: int, status: str = "observed") -> None:
        item = self._lifecycle.setdefault(
            phase,
            {
                "first_action": action_id,
                "last_action": action_id,
                "status": status,
                "observations": 0,
            },
        )
        item["last_action"] = action_id
        item["status"] = status
        item["observations"] += 1

    @staticmethod
    def _search_anchors(output: str, *, limit: int = 8) -> list[dict[str, Any]]:
        """Parse ``path:line:text`` anchors from search output."""
        anchors: list[dict[str, Any]] = []
        for line in (output or "").splitlines():
            match = re.match(r"^([^:\s][^:]*):(\d+):(.*)$", line)
            if not match:
                continue
            path = match.group(1).strip()
            try:
                line_no = int(match.group(2))
            except ValueError:
                continue
            text = match.group(3).strip()
            anchors.append({"path": path, "line": line_no, "text": text[:80]})
            if len(anchors) >= limit:
                break
        return anchors

    @staticmethod
    def _spec(feature_id: str) -> dict[str, str]:
        return next(item for item in CENTRAL_FEATURES if item["id"] == feature_id)

    def _emit(
        self,
        feature_id: str,
        *,
        boundary: str,
        action_id: int,
        revision: str,
        decision: str = "DELIVERED",
        reason: str,
        payload: dict[str, Any] | None = None,
        source_revision: str | None = None,
        source_epoch: int | None = None,
    ) -> None:
        if not self.enabled:
            return
        key = (feature_id, action_id, revision)
        if key in self._seen:
            return
        self._seen.add(key)
        spec = self._spec(feature_id)
        candidate_payload = payload or self._payload(feature_id, boundary, reason)
        if not feature_payload_valid(
            feature_id,
            candidate_payload,
            boundary=boundary,
            revision=revision,
            fresh=True,
        ):
            return
        self.receipts.append(
            FeatureReceipt(
                feature_id=feature_id,
                kind=spec["kind"],
                boundary=boundary,
                action_id=action_id,
                revision=revision,
                decision=decision,
                reason=reason,
                payload=candidate_payload,
                fresh=True,
                model_visible=self._is_model_actionable(feature_id, decision, candidate_payload),
                source_revision=source_revision if source_revision is not None else revision,
                source_epoch=(
                    source_epoch if source_epoch is not None else self._source_epoch
                ),
            )
        )
        self._route_effect(self.receipts[-1])

    @staticmethod
    def _payload(feature_id: str, boundary: str, reason: str) -> dict[str, Any]:
        messages = {
            "caller_contract": "Inspect the verified callers before changing this callable.",
            "covering_red": "A validation command failed; inspect its result before changing code.",
            "def_partition": "Separate definitions from references before editing.",
            "localization": "Inspect the most relevant source locations from the search result.",
            "newfile_precedent": "Follow the verified repository precedent for the new file.",
            "obligations": "Keep the requested task requirements in scope.",
            "recovery": (
                "The same failure repeated; change the hypothesis before exploring further."
            ),
            "signature_delta": "Inspect and repair callers affected by the signature edit.",
            "submit_refusal": "Resolve the fresh required failure before submitting again.",
            "syntax_result": "Repair the syntax or compiler failure on the edited file.",
        }
        return {
            "message": messages.get(feature_id, "Review the runtime evidence before continuing."),
            "boundary": boundary,
            "reason": reason,
        }

    @classmethod
    def _explicit_signature_replacement(cls, command: str) -> tuple[str, str] | None:
        """Return deterministic before/after fragments from an explicit substitution."""
        if not re.search(r"\bsed\s+-i\b", command, re.I):
            return None
        match = re.search(r"s(?P<sep>[/#|])(?P<before>.*?)(?P=sep)(?P<after>.*?)(?P=sep)", command)
        if not match:
            return None
        before = match.group("before")
        after = match.group("after")
        if before == after or not cls._SIGNATURE.search(f"{before}("):
            return None
        if not cls._SIGNATURE.search(f"{after}("):
            return None
        return before[:120], after[:120]

    @staticmethod
    def _source_signatures(path: str, content: str) -> dict[str, str]:
        """Extract deterministic callable signatures from a bounded source witness."""
        signatures: dict[str, str] = {}
        if path.lower().endswith(".py"):
            try:
                tree = ast.parse(content)
            except SyntaxError:
                tree = None
            if tree is not None:
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    args = ast.unparse(node.args)
                    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                    signatures[node.name] = f"{prefix} {node.name}({args})"
                return signatures
        pattern = re.compile(
            r"^\s*(?:async\s+)?(?:def|function|func|sub|procedure)\s+"
            r"(?P<name>[A-Za-z_]\w*)\s*\([^\n]{0,240}\)",
            re.I | re.M,
        )
        for match in pattern.finditer(content):
            signatures[match.group("name")] = " ".join(match.group(0).split())[:280]
        return signatures

    @classmethod
    def _semantic_signature_deltas(
        cls, transition: WorkspaceTransition
    ) -> list[dict[str, str]]:
        deltas: list[dict[str, str]] = []
        for path in sorted(set(transition.before_contents) & set(transition.after_contents)):
            before = cls._source_signatures(path, transition.before_contents[path])
            after = cls._source_signatures(path, transition.after_contents[path])
            for symbol in sorted(set(before) & set(after)):
                if before[symbol] == after[symbol]:
                    continue
                deltas.append(
                    {
                        "path": path,
                        "symbol": symbol,
                        "before_signature": before[symbol],
                        "after_signature": after[symbol],
                    }
                )
        return deltas

    def begin_task(
        self,
        instruction: str,
        *,
        revision: str,
        source_revision: str | None = None,
        explicit_checks: Iterable[str] = (),
        task_deliverables: Iterable[str] = (),
    ) -> None:
        if not self.enabled:
            return
        self._explicit_checks = tuple(explicit_checks)
        self._task_deliverables = set(task_deliverables)
        self._mark_lifecycle("task_started", action_id=0)
        if instruction.strip():
            self._mark_lifecycle("contract_captured", action_id=0)
            self.record_producer_event(
                feature_id="obligations",
                action_id=0,
                kind="contract_captured",
                detail="task requirements and declared checks entered the engine contract",
            )
            self._emit(
                "obligations",
                boundary="task_start",
                action_id=0,
                revision=revision,
                source_revision=source_revision,
                reason="non_empty_task_instruction",
                payload={
                    "requirements_present": True,
                    "obligation_ids": list(self._explicit_checks)
                    or sorted(self._task_deliverables)
                    or ["task:instruction"],
                    "declared_checks": list(self._explicit_checks),
                    "message": self._payload(
                        "obligations", "task_start", "non_empty_task_instruction"
                    )["message"],
                },
            )

    def _is_model_actionable(
        self, feature_id: str, decision: str, payload: dict[str, Any]
    ) -> bool:
        """Expose only novel engine control evidence, never passive receipts."""
        if not self.model_visible or decision != "DELIVERED":
            return False
        actionable = feature_id in _MODEL_ACTIONABLE_FEATURES or (
            feature_id == "GT_EDIT_CHECK" and payload.get("intervention") == "validation_debt"
        ) or (
            feature_id == "GT_LOC_RESLOT"
            and int(payload.get("discarded_anchor_count") or 0) > 0
        )
        return actionable and feature_payload_grounded(feature_id, payload)

    def observe_action(
        self,
        *,
        action_id: int,
        command: str,
        output: str,
        returncode: int,
        transition: WorkspaceTransition,
        revision: str,
        source_revision: str | None = None,
        snapshot: WorkspaceSnapshot | None = None,
        validation: ValidationClassification | None = None,
    ) -> None:
        if not self.enabled:
            return
        normalized = normalize_command(command)
        source_rev = source_revision if source_revision is not None else revision
        classification = validation or classify_validation_command(
            command, self._explicit_checks
        )
        is_search = bool(self._SEARCH.search(normalized))
        self._action_metrics["observed_actions"] += 1
        self._action_metrics["successful_actions" if returncode == 0 else "failed_actions"] += 1
        self._action_metrics["command_chars"] += len(command)
        self._action_metrics["observation_chars"] += len(output or "")
        command_count = self._command_counts.get(normalized, 0) + 1
        self._command_counts[normalized] = command_count
        if command_count > 1:
            self._action_metrics["repeated_commands"] += 1
        if is_search:
            self._action_metrics["search_actions"] += 1
        self._validation_log.append(
            {
                "action": action_id,
                "command": classification.normalized_command,
                "command_class": classification.command_class,
                "is_validation": classification.is_validation,
                "grounded": classification.grounded,
                "declared_check_id": classification.declared_check_id,
                "failure_kind": classification.failure_kind,
                "result_code": classification.result_code,
                "source_revision": source_rev,
                "workspace_revision": revision,
                "diagnostic_fingerprint": classification.diagnostic_fingerprint,
            }
        )
        if classification.is_validation:
            self._action_metrics["check_actions"] += 1
            self._mark_lifecycle("behavior_observed", action_id=action_id)
            if self._workspace_edited:
                self._post_edit_checks += 1
                phase = (
                    "focused_check_validated"
                    if self._post_edit_checks == 1
                    else "regression_validated"
                )
                self._mark_lifecycle(
                    phase,
                    action_id=action_id,
                    status="passed" if returncode == 0 else "failed",
                )
            if classification.declared_check_id:
                self._declared_check_states[classification.declared_check_id] = (
                    "passed" if returncode == 0 else "failed"
                )
            if returncode == 0:
                self._unvalidated_material_edits = 0
                self._validation_debt_notified = False
                self._submit_risk_revisions.discard(source_rev)
                self._emit(
                    "GT_CERT_DELIVERY",
                    boundary="test_result",
                    action_id=action_id,
                    revision=revision,
                    source_revision=source_rev,
                    reason="fresh_validation_pass",
                    payload={
                        "sensor_healthy": snapshot is None or snapshot.healthy,
                        "refused": False,
                        "check_count": 1,
                        "passing_checks": 1,
                        "failing_checks": 0,
                        "readiness": "validated",
                        "checks": [classification.normalized_command[:200]],
                        "message": "Current source revision has fresh passing validation.",
                    },
                )

        classified: dict[str, ClassifiedChange] = {}
        for path in transition.changed_paths:
            kind = "f"
            if snapshot is not None:
                state = snapshot.entries.get(path)
                if state is not None:
                    kind = state.kind
            classified[path] = classify_change(
                path, kind=kind, task_deliverables=self._task_deliverables
            )
        source_relevant = tuple(
            item.path for item in classified.values() if item.validation_relevant
        )
        model_authored = tuple(
            item.path
            for item in classified.values()
            if item.origin == ChangeOrigin.MODEL_AUTHORED
        )
        if transition.changed_paths:
            if model_authored:
                # Any authored source change makes prior check results stale.
                self._source_epoch += 1
                self._recent_source_paths = tuple(model_authored)
                self._declared_check_states = {
                    check: ("stale" if state == "passed" else state)
                    for check, state in self._declared_check_states.items()
                }
            # GT_CHANGE_SURFACE reports every classified change, labeled by
            # origin; derived artifacts are surfaced as facts, never as source.
            self._emit(
                "GT_CHANGE_SURFACE",
                boundary="edit_result",
                action_id=action_id,
                revision=revision,
                source_revision=source_rev,
                reason="workspace_revision_changed",
                payload={
                    "owner_feature": "newfile_precedent",
                    "created": list(transition.created),
                    "modified": list(transition.modified),
                    "deleted": list(transition.deleted),
                    "source_relevant": list(source_relevant),
                    "origins": {
                        origin.value: sum(
                            item.origin == origin for item in classified.values()
                        )
                        for origin in ChangeOrigin
                    },
                    "message": "Workspace change observed: "
                    + ", ".join(list(source_relevant)[:4] or list(transition.changed_paths)[:4]),
                },
            )
            if source_relevant:
                self._workspace_edited = True
                self._unvalidated_material_edits += 1
                self._action_metrics["workspace_change_actions"] += 1
                self._action_metrics["created_paths"] += sum(
                    item.path in transition.created for item in classified.values()
                    if item.validation_relevant
                )
                self._action_metrics["modified_paths"] += sum(
                    item.path in transition.modified for item in classified.values()
                    if item.validation_relevant
                )
                self._action_metrics["deleted_paths"] += sum(
                    item.path in transition.deleted for item in classified.values()
                    if item.validation_relevant
                )
                self._mark_lifecycle("workspace_edited", action_id=action_id)
                self._mark_lifecycle("change_surface_certified", action_id=action_id)
                self.record_producer_event(
                    feature_id="GT_CHANGE_SURFACE",
                    action_id=action_id,
                    kind="source_revision_and_validation_debt",
                    detail=(
                        f"source_epoch={self._source_epoch}; "
                        f"unvalidated_material_edits={self._unvalidated_material_edits}"
                    ),
                )
                changed = list(source_relevant)
                self.record_producer_event(
                    feature_id="GT_PATCH_DELTA",
                    action_id=action_id,
                    kind="validation_surface_registered",
                    detail=", ".join(changed[:8]),
                )
                self._emit(
                    "GT_PATCH_DELTA",
                    boundary="edit_result",
                    action_id=action_id,
                    revision=revision,
                    source_revision=source_rev,
                    reason="non_empty_patch_surface",
                    payload={
                        "owner_feature": "signature_delta",
                        "changed_paths": changed,
                        "message": "Workspace change observed: " + ", ".join(changed[:4]),
                    },
                )
                if self._explicit_checks:
                    self.record_existing_consumer_read(
                        feature_id="obligations",
                        action_id=action_id,
                        purpose="declared_check_selection",
                    )
                    declared_check = select_declared_check(
                        self._explicit_checks, self._declared_check_states
                    )
                    if declared_check:
                        debt = (
                            self._unvalidated_material_edits >= 3
                            and not self._validation_debt_notified
                        )
                        self._emit(
                            "GT_EDIT_CHECK",
                            boundary="edit_result",
                            action_id=action_id,
                            revision=revision,
                            source_revision=source_rev,
                            reason=(
                                "multiple_material_edits_without_validation"
                                if debt
                                else "authored_edit_requires_declared_check"
                            ),
                            payload={
                                "owner_feature": "syntax_result",
                                "intervention": (
                                    "validation_debt" if debt else "validation_schedule"
                                ),
                                "material_edit_count": self._unvalidated_material_edits,
                                "declared_check": declared_check[:120],
                                "changed_paths": changed[:4],
                                "message": f"Relevant declared check: {declared_check[:120]}",
                            },
                        )
                        if debt:
                            self._validation_debt_notified = True
                        self.record_producer_event(
                            feature_id="GT_EDIT_CHECK",
                            action_id=action_id,
                            kind="declared_check_selected",
                            detail=declared_check[:120],
                        )
            else:
                self._action_metrics["no_change_actions"] += 1
        else:
            self._action_metrics["no_change_actions"] += 1
        if is_search and output.strip():
            self._searched = True
            self._mark_lifecycle("location_anchored", action_id=action_id)
            anchors = self._search_anchors(output)
            self.record_producer_event(
                feature_id="localization",
                action_id=action_id,
                kind="location_anchored",
                detail=f"anchors={len(anchors)}",
            )
            self._emit(
                "localization",
                boundary="search_result",
                action_id=action_id,
                revision=revision,
                source_revision=source_rev,
                reason="non_empty_search_result",
                payload={
                    "candidate_locations": True,
                    "anchors": anchors,
                    "query": normalized[:120],
                    "message": self._payload(
                        "localization", "search_result", "non_empty_search_result"
                    )["message"],
                },
            )
            self._emit(
                "GT_LOC_RESLOT",
                boundary="search_result",
                action_id=action_id,
                revision=revision,
                source_revision=source_rev,
                reason="ranked_anchors_selected",
                payload={
                    "owner_feature": "localization",
                    "selected_anchors": anchors[:4],
                    "discarded_anchor_count": max(0, len(anchors) - 4),
                    "message": "Ranked source anchors selected for the next observation.",
                },
            )
            self.record_producer_event(
                feature_id="GT_LOC_RESLOT",
                action_id=action_id,
                kind="ranked_anchors_computed",
                detail=f"selected={min(4, len(anchors))}; discarded={max(0, len(anchors) - 4)}",
            )
            definition_anchors = [
                anchor for anchor in anchors if self._DEFINITION.search(anchor["text"])
            ]
            reference_anchors = [
                anchor for anchor in anchors if not self._DEFINITION.search(anchor["text"])
            ]
            if definition_anchors:
                self.record_producer_event(
                    feature_id="def_partition",
                    action_id=action_id,
                    kind="definition_reference_partitioned",
                    detail=f"definitions={len(definition_anchors)}; references={len(reference_anchors)}",
                )
                self._emit(
                    "def_partition",
                    boundary="search_result",
                    action_id=action_id,
                    revision=revision,
                    source_revision=source_rev,
                    reason="definitions_and_references_present",
                    payload={
                        "definitions": True,
                        "references": True,
                        "definition_anchors": definition_anchors,
                        "reference_anchors": reference_anchors,
                        "message": self._payload(
                            "def_partition", "search_result", "definitions_and_references_present"
                        )["message"],
                    },
                )
            callers = reference_anchors
            if definition_anchors and callers:
                self._mark_lifecycle("impact_captured", action_id=action_id)
                self.record_producer_event(
                    feature_id="caller_contract",
                    action_id=action_id,
                    kind="caller_impact_captured",
                    detail=f"callers={len(callers)}",
                )
                self._emit(
                    "caller_contract",
                    boundary="search_result",
                    action_id=action_id,
                    revision=revision,
                    source_revision=source_rev,
                    reason="definition_and_reference_anchors_present",
                    payload={
                        "callers_verified": True,
                        "callers": callers,
                        "message": self._payload(
                            "caller_contract",
                            "search_result",
                            "definition_and_reference_anchors_present",
                        )["message"],
                    },
                )

        failure_kind = classify_failure_kind(returncode, output)
        if (
            returncode != 0
            and classification.is_validation
            and failure_kind == "validation_failure"
        ):
            check_phase = "post_edit" if self._workspace_edited else "reproduction"
            self.record_existing_consumer_read(
                feature_id="GT_CHANGE_SURFACE",
                action_id=action_id,
                purpose="failure_phase_selection",
            )
            bounded_diagnostic = " ".join(
                line.strip()
                for line in (output or "").splitlines()
                if self._FAILURE.search(line)
            )[:240]
            self.record_producer_event(
                feature_id="covering_red",
                action_id=action_id,
                kind="failure_state_keyed",
                detail=f"phase={check_phase}; fingerprint={classification.diagnostic_fingerprint}",
            )
            self._emit(
                "covering_red",
                boundary="test_result",
                action_id=action_id,
                revision=revision,
                source_revision=source_rev,
                reason="failed_check_or_failure_output",
                payload={
                    "check_failed": True,
                    "returncode": returncode,
                    "phase": check_phase,
                    "command": classification.normalized_command[:200],
                    "command_class": classification.command_class,
                    "failure_kind": failure_kind,
                    "attribution": (
                        classification.declared_check_id or classification.command_class
                    ),
                    "diagnostic": bounded_diagnostic,
                    "message": self._payload(
                        "covering_red", "test_result", "failed_check_or_failure_output"
                    )["message"],
                },
            )
            failure_fingerprint = classification.diagnostic_fingerprint
            failure_key = (normalized, failure_fingerprint, returncode, source_rev)
            count = self._failed_actions.get(failure_key, 0) + 1
            self._failed_actions[failure_key] = count
            self.record_producer_event(
                feature_id="GT_HYPOTHESIS",
                action_id=action_id,
                kind="failure_repeat_count_updated",
                detail=f"repeat_count={count}",
            )
            self._emit(
                "GT_HYPOTHESIS",
                boundary="test_result",
                action_id=action_id,
                revision=revision,
                source_revision=source_rev,
                reason="deterministic_failure_state_transition",
                payload={
                    "owner_feature": "recovery",
                    "failure_fingerprint": failure_fingerprint,
                    "repeat_count": count,
                    "message": "A deterministic validation failure state was recorded.",
                },
            )
            blocker = classification.declared_check_id or classification.normalized_command[:200]
            blockers = [blocker] if blocker else []
            if (
                blockers
                and bounded_diagnostic
                and source_rev not in self._submit_risk_revisions
            ):
                self._submit_risk_revisions.add(source_rev)
                self.record_producer_event(
                    feature_id="GT_SS_SUBMIT_RED",
                    action_id=action_id,
                    kind="submit_risk_latched",
                    detail=f"source_revision={source_rev}",
                )
                self._emit(
                    "GT_SS_SUBMIT_RED",
                    boundary="test_result",
                    action_id=action_id,
                    revision=revision,
                    source_revision=source_rev,
                    reason="fresh_grounded_failure",
                    payload={
                        "owner_feature": "submit_refusal",
                        "submission_risk": True,
                        "blockers": blockers,
                        "failure_fingerprint": failure_fingerprint,
                        "message": "Current source revision retains a failing required check.",
                    },
                )
                self._emit(
                    "submit_refusal",
                    boundary="test_result",
                    action_id=action_id,
                    revision=revision,
                    source_revision=source_rev,
                    reason="fresh_grounded_failure",
                    payload={
                        "submission_risk": True,
                        "refused": False,
                        "fresh_failure": True,
                        "blockers": blockers,
                        "message": (
                            "The current source revision still has a failing required check: "
                            + ", ".join(blockers[:2])
                        ),
                    },
                )
                self.record_producer_event(
                    feature_id="submit_refusal",
                    action_id=action_id,
                    kind="submit_risk_latched",
                    detail=f"blockers={len(blockers)}",
                )
            if count >= 2:
                self._emit(
                    "recovery",
                    boundary="test_result",
                    action_id=action_id,
                    revision=revision,
                    source_revision=source_rev,
                    reason="same_failure_repeated",
                    payload={
                        "repeat_count": count,
                        "failure_fingerprint": failure_fingerprint,
                        "alternate_action": {
                            "kind": "inspect_then_edit",
                            "paths": list(self._recent_source_paths),
                            "discriminator": "exact repeat at unchanged source revision",
                        },
                        "message": (
                            "The same validation failure repeated at an unchanged source "
                            "revision; inspect and edit the anchored source before rerunning."
                        ),
                    },
                )

        if transition.created:
            available_paths = set(transition.before_contents)
            if snapshot is not None:
                available_paths.update(snapshot.entries)
            precedent_path = ""
            for created_path in transition.created:
                parent = created_path.rsplit("/", 1)[0] if "/" in created_path else ""
                suffix = "." + created_path.rsplit(".", 1)[-1] if "." in created_path else ""
                candidates = sorted(
                    path
                    for path in available_paths
                    if path not in transition.created
                    and (path.rsplit("/", 1)[0] if "/" in path else "") == parent
                    and (not suffix or path.lower().endswith(suffix.lower()))
                )
                if candidates:
                    precedent_path = candidates[0]
                    break
            if precedent_path:
                self._precedent_verified = True
                self._precedent_path = precedent_path
                self.record_producer_event(
                    feature_id="newfile_precedent",
                    action_id=action_id,
                    kind="precedent_verified",
                    detail=precedent_path,
                )
                self._emit(
                    "newfile_precedent",
                    boundary="edit_result",
                    action_id=action_id,
                    revision=revision,
                    source_revision=source_rev,
                    reason="new_file_with_concrete_sibling_precedent",
                    payload={
                        "created_files": list(transition.created),
                        "precedent_verified": True,
                        "precedent_path": precedent_path,
                        "message": (
                            f"New source file {transition.created[0]} has repository "
                            f"precedent {precedent_path}."
                        ),
                    },
                )

        signature_deltas = self._semantic_signature_deltas(transition)
        if not signature_deltas:
            signature_replacement = self._explicit_signature_replacement(normalized)
            if transition.changed_paths and signature_replacement:
                before_signature, after_signature = signature_replacement
                symbol_match = re.search(
                    r"\b(?:def|function|func|sub|procedure|class)\s+([A-Za-z_]\w*)\s*\(",
                    before_signature,
                )
                signature_deltas = [
                    {
                        "path": transition.changed_paths[0],
                        "symbol": symbol_match.group(1) if symbol_match else "",
                        "before_signature": before_signature,
                        "after_signature": after_signature,
                    }
                ]
        if signature_deltas:
            primary = signature_deltas[0]
            caller_payload = self._controller_state.impact.get("caller_contract") or {}
            if caller_payload:
                self.record_existing_consumer_read(
                    feature_id="caller_contract",
                    action_id=action_id,
                    purpose="signature_delta_caller_impact",
                )
            callers = list(caller_payload.get("callers") or [])
            contributors = ["signature_delta", "GT_PATCH_DELTA"]
            if callers:
                contributors.append("caller_contract")
            self._emit(
                "signature_delta",
                boundary="edit_result",
                action_id=action_id,
                revision=revision,
                source_revision=source_rev,
                reason="signature-shaped edit on changed path",
                payload={
                    "changed_paths": list(transition.changed_paths),
                    "signature_edit": True,
                    "symbol": primary["symbol"],
                    "before_signature": primary["before_signature"],
                    "after_signature": primary["after_signature"],
                    "signature_deltas": signature_deltas,
                    "callers": callers,
                    "contributing_features": contributors,
                    "signature_fingerprint": hashlib.sha256(
                        repr(signature_deltas).encode("utf-8", "replace")
                    ).hexdigest()[:16],
                    "message": self._payload(
                        "signature_delta", "edit_result", "signature-shaped edit on changed path"
                    )["message"],
                },
            )

    def record_syntax(
        self,
        *,
        action_id: int,
        revision: str,
        failed: bool,
        reason: str,
        path: str = "",
        command: str = "",
        returncode: int | None = None,
        diagnostic: str = "",
        source_revision: str | None = None,
    ) -> None:
        self._action_metrics["lint_checks"] += 1
        self._action_metrics["lint_failures" if failed else "lint_passes"] += 1
        self._action_metrics["engine_actions"] += 1
        self.record_producer_event(
            feature_id="syntax_result",
            action_id=action_id,
            kind="validation_result_recorded",
            detail=f"failed={failed}; path={path}",
        )
        self._mark_lifecycle(
            "static_validated",
            action_id=action_id,
            status="failed" if failed else "passed",
        )
        message = self._payload("syntax_result", "edit_result", reason)["message"]
        if failed and path:
            concise = " ".join(diagnostic.split())[:120]
            message = f"Repair the syntax failure in {path}"
            if concise:
                message += f": {concise}"
        self._emit(
            "syntax_result",
            boundary="edit_result",
            action_id=action_id,
            revision=revision,
            source_revision=source_revision,
            decision="DELIVERED" if failed else "PASS",
            reason=reason,
            payload={
                "ok": not failed,
                "fresh": True,
                "path": path,
                "command": command,
                "returncode": returncode,
                "message": message,
            },
        )

    def record_submit(
        self,
        *,
        action_id: int,
        revision: str,
        refused: bool,
        sensor_healthy: bool,
        check_count: int = 0,
        passing_checks: int = 0,
        failing_checks: int = 0,
        blockers: tuple[str, ...] = (),
        source_revision: str | None = None,
    ) -> None:
        self._action_metrics["submit_attempts"] += 1
        self.record_producer_event(
            feature_id="GT_CERT_DELIVERY",
            action_id=action_id,
            kind="submission_readiness_evaluated",
            detail=f"healthy={sensor_healthy}; checks={check_count}",
        )
        if refused:
            self._action_metrics["submit_risks"] += 1
            self.record_producer_event(
                feature_id="submit_refusal",
                action_id=action_id,
                kind="submit_refusal_evaluated",
                detail=f"blockers={len(blockers)}",
            )
        elif sensor_healthy and passing_checks > 0:
            self._mark_lifecycle("submit_ready", action_id=action_id, status="passed")
        if refused:
            self._emit(
                "submit_refusal",
                boundary="submit",
                action_id=action_id,
                revision=revision,
                source_revision=source_revision,
                reason="fresh_grounded_failure",
                payload={
                    "submission_risk": True,
                    "refused": True,
                    "fresh_failure": True,
                    "blockers": list(blockers),
                    "message": self._payload("submit_refusal", "submit", "fresh_grounded_failure")[
                        "message"
                    ],
                },
            )
            self._emit(
                "GT_SS_SUBMIT_RED",
                boundary="submit",
                action_id=action_id,
                revision=revision,
                source_revision=source_revision,
                reason="fresh_grounded_failure",
                payload={
                    "owner_feature": "submit_refusal",
                    "submission_risk": True,
                    "blockers": list(blockers),
                    "message": "Current source revision retains a failing required check.",
                },
            )
        self._emit(
            "GT_CERT_DELIVERY",
            boundary="submit",
            action_id=action_id,
            revision=revision,
            source_revision=source_revision,
            decision="DELIVERED" if sensor_healthy else "PASS",
            reason="submission_readiness_receipt",
            payload={
                "sensor_healthy": sensor_healthy,
                "refused": refused,
                "check_count": check_count,
                "passing_checks": passing_checks,
                "failing_checks": failing_checks,
                "readiness": (
                    "blocked"
                    if refused
                    else "validated"
                    if sensor_healthy and passing_checks > 0 and failing_checks == 0
                    else "unverified"
                ),
                "message": (
                    "Submission readiness has current passing check evidence."
                    if sensor_healthy and passing_checks > 0 and failing_checks == 0
                    else "Submission readiness was evaluated without claiming validation."
                ),
            },
        )

    def _route_effect(self, receipt: FeatureReceipt) -> None:
        """Route one produced receipt to its registered consumer."""
        spec = consumer_spec_for(receipt.feature_id)
        if spec is None:
            return
        effect = FeatureEffect(
            feature_id=receipt.feature_id,
            receipt_id=f"receipt-{len(self.receipts)}",
            effect_kind=spec.effect_kind,
            effect_action=dict(receipt.payload),
            required_before_action=(
                receipt.action_id if spec.required_before_next_action else None
            ),
            model_visible=bool(spec.model_visible and receipt.model_visible),
            evidence_action=receipt.action_id,
        )
        self._effects.append(effect)
        self._consumer_paths.setdefault(receipt.feature_id, []).append(
            spec.effect_kind.value
        )

    def record_producer_event(
        self,
        *,
        feature_id: str,
        action_id: int,
        kind: str,
        detail: str,
    ) -> None:
        """Record producer-side engine work without changing runtime policy."""
        self._producer_events.append(
            {
                "feature_id": feature_id,
                "action": action_id,
                "kind": kind,
                "detail": detail,
            }
        )

    @staticmethod
    def _controller_state_hash(state: CentralControllerState) -> str:
        return hashlib.sha256(
            repr(state.as_dict()).encode("utf-8", "replace")
        ).hexdigest()

    def _apply_effect(self, effect: FeatureEffect, *, call: int) -> None:
        """Reduce one consumed feature payload into authoritative controller state."""
        state = self._controller_state
        before = self._controller_state_hash(state)
        payload = dict(effect.effect_action)
        section_by_feature = {
            "obligations": "contract",
            "localization": "localization",
            "GT_LOC_RESLOT": "localization",
            "def_partition": "impact",
            "caller_contract": "impact",
            "newfile_precedent": "impact",
            "GT_CHANGE_SURFACE": "change_surface",
            "GT_PATCH_DELTA": "patch_delta",
            "signature_delta": "patch_delta",
            "GT_EDIT_CHECK": "validation_plan",
            "syntax_result": "validation_results",
            "covering_red": "failure_state",
            "GT_HYPOTHESIS": "failure_state",
            "recovery": "failure_state",
            "submit_refusal": "submission_state",
            "GT_SS_SUBMIT_RED": "submission_state",
            "GT_CERT_DELIVERY": "certificate",
        }
        section_name = section_by_feature[effect.feature_id]
        section = getattr(state, section_name)
        section[effect.feature_id] = {
            **payload,
            "evidence_action": effect.evidence_action,
            "applied_before_call": call + 1,
        }
        receipt = next(
            (item for item in reversed(self.receipts) if item.feature_id == effect.feature_id
             and item.action_id == effect.evidence_action),
            None,
        )
        if receipt is not None:
            state.source_revision = receipt.source_revision
            state.workspace_revision = receipt.revision
        after = self._controller_state_hash(state)
        self._effect_applications.append(
            {
                "feature_id": effect.feature_id,
                "receipt_id": effect.receipt_id,
                "effect_kind": effect.effect_kind.value,
                "evidence_action": effect.evidence_action,
                "source_revision": state.source_revision,
                "workspace_revision": state.workspace_revision,
                "state_fields_changed": [section_name] if before != after else [],
                "state_hash_before": before,
                "state_hash_after": after,
                "delivery_candidate": effect.model_visible,
                "private_consequence": "" if effect.model_visible else section_name,
                "quiet_reason": "" if before != after else "duplicate_state",
                "applied_before_call": call + 1,
            }
        )
        producer_events = [
            event
            for event in self._producer_events
            if event["feature_id"] == effect.feature_id
            and event["action"] == effect.evidence_action
        ]
        self._effect_trace.append(
            {
                "effect_id": effect.receipt_id,
                "feature_id": effect.feature_id,
                "effect_kind": effect.effect_kind.value,
                "evidence_action": effect.evidence_action,
                "applied_call": call,
                "state_fields_changed": [section_name] if before != after else [],
                "state_reads": [],
                "actuator_events": [
                    {
                        "kind": "producer_engine_event",
                        "action": event["action"],
                        "event": event["kind"],
                        "detail": event["detail"],
                    }
                    for event in producer_events
                ],
                "provider_delivery_ids": [],
                "disposition": (
                    "engine_internal_state" if producer_events else "audit_only"
                ),
                "timing": {
                    "evidence_before_effect": (
                        effect.applied_after_action is not None
                        and effect.applied_after_action >= effect.evidence_action
                    ),
                    "late": effect.late,
                    "predictive": effect.predictive,
                },
            }
        )

    def _trace_for_effect(
        self, feature_id: str, *, evidence_action: int | None = None
    ) -> dict[str, Any] | None:
        candidates = [
            row
            for row in self._effect_trace
            if row["feature_id"] == feature_id
            and (evidence_action is None or row["evidence_action"] == evidence_action)
        ]
        return candidates[-1] if candidates else None

    def record_existing_consumer_read(
        self, *, feature_id: str, action_id: int, purpose: str
    ) -> None:
        """Record an existing state read without changing runtime behavior."""
        row = self._trace_for_effect(feature_id)
        if row is None:
            return
        row["state_reads"].append(
            {"action": action_id, "purpose": purpose}
        )
        if row["disposition"] == "audit_only":
            row["disposition"] = "existing_engine_actuation"
        row["actuator_events"].append(
            {"kind": "existing_consumer_read", "action": action_id, "purpose": purpose}
        )

    def record_provider_delivery(
        self, *, effect_ids: Iterable[str], delivery_id: str
    ) -> None:
        """Link a confirmed provider delivery to its contributing effects."""
        ids = set(effect_ids)
        for row in self._effect_trace:
            if row["effect_id"] not in ids:
                continue
            row["provider_delivery_ids"].append(delivery_id)
            row["actuator_events"].append(
                {"kind": "provider_payload", "delivery_id": delivery_id}
            )
            row["disposition"] = "provider_payload"

    def consume_effects(self, *, action_id: int, call: int) -> list[FeatureEffect]:
        """Return effects produced since the last consume, with timing bound."""
        fresh = self._effects[self._effect_cursor :]
        self._effect_cursor = len(self._effects)
        consumed: list[FeatureEffect] = []
        for offset, effect in enumerate(fresh):
            applied = max(effect.evidence_action, action_id)
            required = effect.required_before_action
            updated = replace(
                effect,
                applied_after_action=applied,
                delivered_before_call=call,
                predecided_actions_executed_after_evidence=max(
                    0, applied - effect.evidence_action - 1
                ),
                late=required is not None and applied > required,
                # `consume_effects` runs after the action has returned its
                # evidence.  Applying at that same action is immediate; a
                # predictive effect would have to precede its evidence.
                predictive=applied < effect.evidence_action,
            )
            self._effects[self._effect_cursor - len(fresh) + offset] = updated
            self._apply_effect(updated, call=call)
            consumed.append(updated)
        return consumed

    def record_skipped_action(self, *, action_id: int) -> None:
        """Count one pre-decided action cancelled by an immediate control."""
        self._action_metrics["interrupted_actions"] += 1
        self._mark_lifecycle("batch_interrupted", action_id=action_id)

    def record_predecided_continuation(self, *, evidence_action: int, executed: int) -> None:
        """Audit actions already chosen in the same model response; never cancel them."""
        if executed <= 0:
            return
        for index, effect in enumerate(self._effects):
            if effect.evidence_action == evidence_action:
                self._effects[index] = replace(
                    effect,
                    predecided_actions_executed_after_evidence=executed,
                )

    def record_batch_interrupt(self, *, action_id: int, cancelled: int, reason: str) -> None:
        self._action_metrics["batch_interrupts"] += 1
        self._batch_interrupts.append(
            {"evidence_action": action_id, "cancelled": cancelled, "reason": reason}
        )
        for index, effect in enumerate(self._effects):
            if (
                effect.evidence_action == action_id
                and effect.required_before_action is not None
            ):
                self._effects[index] = replace(
                    effect, predecided_actions_cancelled=cancelled
                )

    def summary(self) -> dict[str, Any]:
        by_feature = {feature_id: 0 for feature_id in CENTRAL_FEATURE_IDS}
        for receipt in self.receipts:
            by_feature[receipt.feature_id] += 1
        return {
            "enabled": self.enabled,
            "feature_count": len(CENTRAL_FEATURE_IDS),
            "feature_ids": list(CENTRAL_FEATURE_IDS),
            "guidance_events": self._guidance_events,
            "guidance_chars": self._guidance_chars,
            "guidance_features": list(self._guidance_features),
            "guidance_candidates": self._guidance_candidates,
            "guidance_suppressed": self._guidance_suppressed,
            "guidance_by_feature": {
                feature_id: self._guidance_features.count(feature_id)
                for feature_id in dict.fromkeys(self._guidance_features)
            },
            "action_metrics": dict(self._action_metrics),
            "lifecycle": dict(self._lifecycle),
            "produced_counts": by_feature,
            "consumer_paths": dict(self._consumer_paths),
            "effects": [effect.as_dict() for effect in self._effects],
            "effect_applications": list(self._effect_applications),
            "effect_trace": [dict(row) for row in self._effect_trace],
            "producer_events": list(self._producer_events),
            "controller_state": self._controller_state.as_dict(),
            "batch_interrupts": list(self._batch_interrupts),
            "source_epoch": self._source_epoch,
            "validation_log": list(self._validation_log),
            "declared_check_states": dict(self._declared_check_states),
            "receipts": [
                {
                    "feature_id": item.feature_id,
                    "kind": item.kind,
                    "boundary": item.boundary,
                    "action": item.action_id,
                    "revision": item.revision,
                    "decision": item.decision,
                    "reason": item.reason,
                    "payload": item.payload,
                    "fresh": item.fresh,
                    "model_visible": item.model_visible,
                    "source_revision": item.source_revision,
                    "source_epoch": item.source_epoch,
                }
                for item in self.receipts
            ],
        }

    def _record_guidance(self, metadata: dict[str, Any]) -> None:
        feedback = str(metadata["feedback"])
        feature_id = str(metadata["feature_id"])
        delivery_id = str(metadata.get("delivery_id") or f"guidance-{self._guidance_events + 1}")
        metadata["delivery_id"] = delivery_id
        self.record_provider_delivery(
            effect_ids=metadata.get("effect_ids") or (),
            delivery_id=delivery_id,
        )
        self._guidance_events += 1
        self._guidance_chars += len(feedback)
        self._guidance_features.append(feature_id)

    def prepared_guidance(self) -> dict[str, Any] | None:
        return dict(self._prepared_guidance) if self._prepared_guidance else None

    def confirm_prepared_guidance(self) -> dict[str, Any] | None:
        """Count a deferred advisory only when it reaches a model request."""
        if self._prepared_guidance is None:
            return None
        metadata = self._prepared_guidance
        self._prepared_guidance = None
        self._record_guidance(metadata)
        return dict(metadata)

    def discard_model_feedback(self) -> None:
        """Consume candidates superseded by a direct submit-hold observation."""
        fresh_receipts = self.receipts[self._feedback_cursor :]
        self._feedback_cursor = len(self.receipts)
        for item in fresh_receipts:
            if item.model_visible and item.payload.get("message"):
                self._guidance_candidates += 1
            self._guidance_suppressed += 1

    @staticmethod
    def _render_feature_fact(item: FeatureReceipt) -> str:
        payload = item.payload
        feature_id = item.feature_id
        if feature_id == "syntax_result":
            diagnostic = " ".join(str(payload.get("diagnostic") or "").split())
            outcome = diagnostic or f"return code {payload.get('returncode')}"
            return (
                f"Syntax check failed for {payload.get('path')} using "
                f"{payload.get('command')}: {outcome}."
            )
        if feature_id == "covering_red":
            return (
                f"Validation failed for the current source revision using "
                f"{payload.get('command')} ({payload.get('attribution')}): "
                f"{' '.join(str(payload.get('diagnostic') or '').split())}."
            )
        if feature_id == "recovery":
            alternate = payload.get("alternate_action") or {}
            paths = ", ".join(alternate.get("paths") or ())
            return (
                f"The same validation failure repeated {payload.get('repeat_count')} times "
                f"without a source revision change; inspect {paths or 'the last changed source'} "
                f"to test: {alternate.get('discriminator')}."
            )
        if feature_id == "signature_delta":
            paths = ", ".join(payload.get("changed_paths") or ())
            caller_paths = ", ".join(
                str(item.get("path") or "") for item in payload.get("callers") or ()
            )
            caller_fact = f" Known callers: {caller_paths}." if caller_paths else ""
            return (
                f"Signature changed for {payload.get('symbol')} in {paths}: "
                f"{payload.get('before_signature')} -> {payload.get('after_signature')}."
                + caller_fact
            )
        if feature_id == "newfile_precedent":
            created = ", ".join(payload.get("created_files") or ())
            return (
                f"New file {created} has concrete repository precedent "
                f"{payload.get('precedent_path')}."
            )
        if feature_id == "GT_LOC_RESLOT":
            anchors = payload.get("selected_anchors") or ()
            rendered = ", ".join(
                f"{item.get('path')}:{item.get('line')}" for item in anchors
            )
            return f"Highest-ranked source anchors: {rendered}."
        if feature_id == "submit_refusal":
            return (
                "Current source revision still has a failing required check: "
                + ", ".join(payload.get("blockers") or ())
                + "."
            )
        if feature_id == "GT_EDIT_CHECK":
            paths = ", ".join(payload.get("changed_paths") or ())
            return (
                f"Unvalidated authored changes in {paths}; declared check: "
                f"{payload.get('declared_check')}."
            )
        return ""

    def model_feedback(self, *, limit: int = 320, deferred: bool = False) -> str:
        """Return one bounded, highest-priority advisory for this action."""
        fresh_receipts = self.receipts[self._feedback_cursor :]
        self._feedback_cursor = len(self.receipts)
        visible: list[FeatureReceipt] = []
        for item in fresh_receipts:
            if (
                not item.model_visible
                or not item.payload.get("message")
                or not feature_payload_grounded(item.feature_id, item.payload)
            ):
                self._guidance_suppressed += 1
                continue
            self._guidance_candidates += 1
            evidence_fingerprint = hashlib.sha256(
                repr(sorted(item.payload.items())).encode("utf-8", "replace")
            ).hexdigest()[:16]
            key = (item.feature_id, item.revision, evidence_fingerprint)
            # The feature and revision are the operative evidence boundary.
            # Payload wording or action IDs must not re-inject the same fact.
            revision_key = (item.feature_id, item.revision, "")
            if key in self._guided_keys or revision_key in self._guided_keys:
                self._guidance_suppressed += 1
                continue
            visible.append(item)
        if not visible:
            return ""
        priority = {
            "syntax_result": 0,
            "covering_red": 0,
            "recovery": 1,
            "signature_delta": 2,
            "newfile_precedent": 2,
            "GT_EDIT_CHECK": 3,
            "GT_LOC_RESLOT": 4,
            "submit_refusal": 4,
        }
        ordered = sorted(
            enumerate(visible),
            key=lambda item: (priority.get(item[1].feature_id, 10), item[0]),
        )
        selected_items: list[FeatureReceipt] = []
        facts: list[str] = []
        for _, item in ordered:
            fact = self._render_feature_fact(item)
            if not fact:
                self._guidance_suppressed += 1
                continue
            candidate = " ".join([*facts, fact])
            if facts and len(render_runtime_advisory(candidate, limit=limit)) >= limit:
                self._guidance_suppressed += 1
                continue
            selected_items.append(item)
            facts.append(fact)
            if len(facts) >= 3:
                break
        covering_actions = {
            item.action_id for item in selected_items if item.feature_id == "covering_red"
        }
        for item in visible:
            if (
                item.feature_id == "submit_refusal"
                and item.action_id in covering_actions
                and item not in selected_items
            ):
                # The failure fact already carries the source-bound submission
                # risk.  Credit the actuator as a contributor without adding a
                # second sentence to the model context.
                selected_items.append(item)
        if not selected_items:
            return ""
        feedback = render_runtime_advisory(
            " ".join(facts), limit=limit
        )
        if not feedback:
            self._guidance_suppressed += len(selected_items)
            return ""
        selected_set = {id(item) for item in selected_items}
        self._guidance_suppressed += sum(id(item) not in selected_set for item in visible)
        for item in selected_items:
            self._guided_keys.add((item.feature_id, item.revision, ""))
        selected = selected_items[0]
        contributing_features: list[str] = []
        for item in selected_items:
            for feature_id in [
                item.feature_id,
                *(item.payload.get("contributing_features") or []),
            ]:
                if feature_id not in contributing_features:
                    contributing_features.append(feature_id)
        metadata = {
            "feature_id": selected.feature_id,
            "contributing_features": contributing_features,
            "effect_ids": [
                row["effect_id"]
                for row in self._effect_trace
                if any(
                    row["feature_id"] == item.feature_id
                    and row["evidence_action"] == item.action_id
                    for item in selected_items
                )
            ],
            "evidence_action": selected.action_id,
            "evidence_actions": [item.action_id for item in selected_items],
            "revision": selected.revision,
            "feedback": feedback,
        }
        if deferred:
            self._prepared_guidance = metadata
        else:
            self._record_guidance(metadata)
        return feedback
