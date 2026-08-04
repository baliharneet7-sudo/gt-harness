"""Private state and policy for the host-owned coding-agent runtime.

Nothing in this module is installed in the task container.  The model sees the
stock Mini-SWE Bash interface; this module observes transitions through
Harbor's host-side ``BaseEnvironment`` boundary.
"""

from __future__ import annotations

import hashlib
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
    {"covering_red", "recovery", "signature_delta", "submit_refusal", "syntax_result"}
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


@dataclass(frozen=True, slots=True)
class FileState:
    kind: str
    size: int
    mtime: str
    ctime: str
    link_target: str
    digest: str = ""


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
    "submit_refusal": "submit",
    "syntax_result": "edit_result",
    "GT_CERT_DELIVERY": "submit",
    "GT_CHANGE_SURFACE": "edit_result",
    "GT_EDIT_CHECK": "edit_result",
    "GT_HYPOTHESIS": "test_result",
    "GT_LOC_RESLOT": "search_result",
    "GT_PATCH_DELTA": "edit_result",
    "GT_SS_SUBMIT_RED": "submit",
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
        "submit_refusal": ("refused",),
        "syntax_result": ("ok",),
        "GT_CERT_DELIVERY": ("sensor_healthy", "refused"),
        "GT_CHANGE_SURFACE": ("owner_feature",),
        "GT_EDIT_CHECK": ("owner_feature",),
        "GT_HYPOTHESIS": ("owner_feature",),
        "GT_LOC_RESLOT": ("owner_feature",),
        "GT_PATCH_DELTA": ("owner_feature",),
        "GT_SS_SUBMIT_RED": ("owner_feature",),
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
        if previous is None or not previous.healthy:
            return snapshot

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
        for path, state in tuple(entries.items()):
            old = previous.entries.get(path)
            if old is not None and _same_metadata(old, state) and old.digest:
                entries[path] = replace(state, digest=old.digest)
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
            "submit_attempts": 0,
            "submit_holds": 0,
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
        self._batch_interrupts: list[dict[str, Any]] = []
        self._task_deliverables: set[str] = set()
        self._source_epoch = 0
        self._declared_check_states: dict[str, str] = {}
        self._validation_log: list[dict[str, Any]] = []

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
        # CAP_OWNER delivery is a separate auditable row, not an alias that
        # inflates the FACT count.
        for cap_id, owner in CENTRAL_CAP_OWNERS.items():
            if cap_id == "GT_CERT_DELIVERY":
                # Delivery is emitted at the submit boundary with its own
                # sensor/refusal payload, not as a submit-refusal alias.
                continue
            if owner == feature_id and cap_id not in {
                "GT_CHANGE_SURFACE",
                "GT_HYPOTHESIS",
                "GT_PATCH_DELTA",
            }:
                self._emit(
                    cap_id,
                    boundary=boundary,
                    action_id=action_id,
                    revision=revision,
                    decision=decision,
                    reason=f"owner:{feature_id}",
                    payload={
                        "owner_feature": feature_id,
                        "message": self._payload(feature_id, boundary, reason)["message"],
                    },
                    source_revision=source_revision,
                    source_epoch=source_epoch,
                )

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
            self._emit(
                "obligations",
                boundary="task_start",
                action_id=0,
                revision=revision,
                source_revision=source_revision,
                reason="non_empty_task_instruction",
                payload={
                    "requirements_present": True,
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
        if feature_id in _MODEL_ACTIONABLE_FEATURES:
            return True
        return feature_id == "GT_EDIT_CHECK" and payload.get("intervention") == "validation_debt"

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
                self._declared_check_states = {
                    check: ("stale" if state == "passed" else state)
                    for check, state in self._declared_check_states.items()
                }
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
                changed = list(source_relevant)
                surface_message = "Workspace change observed: " + ", ".join(changed[:4])
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
                        "source_relevant": changed,
                        "origins": {
                            origin.value: sum(
                                item.origin == origin for item in classified.values()
                            )
                            for origin in ChangeOrigin
                        },
                        "message": surface_message,
                    },
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
                        "message": surface_message,
                    },
                )
                if (
                    self._explicit_checks
                    and self._unvalidated_material_edits >= 3
                    and not self._validation_debt_notified
                ):
                    declared_check = select_declared_check(
                        self._explicit_checks, self._declared_check_states
                    )
                    if declared_check:
                        self._emit(
                            "GT_EDIT_CHECK",
                            boundary="edit_result",
                            action_id=action_id,
                            revision=revision,
                            source_revision=source_rev,
                            reason="multiple_material_edits_without_validation",
                            payload={
                                "owner_feature": "syntax_result",
                                "intervention": "validation_debt",
                                "material_edit_count": self._unvalidated_material_edits,
                                "declared_check": declared_check[:120],
                                "changed_paths": changed[:4],
                                "message": (
                                    "Three source revisions have no completed behavioral "
                                    "validation. Run the declared check before another edit: "
                                    f"{declared_check[:120]}"
                                ),
                            },
                        )
                        self._validation_debt_notified = True
            else:
                self._action_metrics["no_change_actions"] += 1
        else:
            self._action_metrics["no_change_actions"] += 1
        if is_search and output.strip():
            self._searched = True
            self._mark_lifecycle("location_anchored", action_id=action_id)
            self._emit(
                "localization",
                boundary="search_result",
                action_id=action_id,
                revision=revision,
                source_revision=source_rev,
                reason="non_empty_search_result",
                payload={
                    "candidate_locations": True,
                    "message": self._payload(
                        "localization", "search_result", "non_empty_search_result"
                    )["message"],
                },
            )
            if self._DEFINITION.search(output) and len(output.splitlines()) >= 2:
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
                        "message": self._payload(
                            "def_partition", "search_result", "definitions_and_references_present"
                        )["message"],
                    },
                )
            if self._CALLSITE.search(output):
                self._mark_lifecycle("impact_captured", action_id=action_id)
                self._emit(
                    "caller_contract",
                    boundary="search_result",
                    action_id=action_id,
                    revision=revision,
                    source_revision=source_rev,
                    reason="verified_caller_language_in_search_result",
                    payload={
                        "callers_verified": True,
                        "message": self._payload(
                            "caller_contract",
                            "search_result",
                            "verified_caller_language_in_search_result",
                        )["message"],
                    },
                )
            if self._PRECEDENT.search(output):
                self._precedent_verified = True
                self._emit(
                    "newfile_precedent",
                    boundary="search_result",
                    action_id=action_id,
                    revision=revision,
                    source_revision=source_rev,
                    reason="precedent_marker_in_search_result",
                    payload={
                        "precedent_verified": True,
                        "message": self._payload(
                            "newfile_precedent",
                            "search_result",
                            "precedent_marker_in_search_result",
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
                    "command_class": classification.command_class,
                    "failure_kind": failure_kind,
                    "attribution": "validation_result_unattributed",
                    "message": self._payload(
                        "covering_red", "test_result", "failed_check_or_failure_output"
                    )["message"],
                },
            )
            failure_fingerprint = classification.diagnostic_fingerprint
            failure_key = (normalized, failure_fingerprint, returncode, source_rev)
            count = self._failed_actions.get(failure_key, 0) + 1
            self._failed_actions[failure_key] = count
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
                        "message": self._payload(
                            "recovery", "test_result", "same_failure_repeated"
                        )["message"],
                    },
                )

        if transition.created and self._precedent_verified:
            self._emit(
                "newfile_precedent",
                boundary="edit_result",
                action_id=action_id,
                revision=revision,
                source_revision=source_rev,
                reason="new_file_after_verified_precedent",
                payload={
                    "created_files": len(transition.created),
                    "message": self._payload(
                        "newfile_precedent",
                        "edit_result",
                        "new_file_after_verified_precedent",
                    )["message"],
                },
            )

        signature_replacement = self._explicit_signature_replacement(normalized)
        if transition.changed_paths and signature_replacement:
            before_signature, after_signature = signature_replacement
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
                    "before_signature": before_signature,
                    "after_signature": after_signature,
                    "signature_fingerprint": hashlib.sha256(
                        f"{before_signature}\0{after_signature}".encode("utf-8", "replace")
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
        source_revision: str | None = None,
    ) -> None:
        self._action_metrics["submit_attempts"] += 1
        if refused:
            self._action_metrics["submit_holds"] += 1
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
                    "refused": True,
                    "fresh_failure": True,
                    "message": self._payload("submit_refusal", "submit", "fresh_grounded_failure")[
                        "message"
                    ],
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
                predictive=applied == effect.evidence_action,
            )
            self._effects[self._effect_cursor - len(fresh) + offset] = updated
            consumed.append(updated)
        return consumed

    def record_skipped_action(self, *, action_id: int) -> None:
        """Count one pre-decided action cancelled by an immediate control."""
        self._action_metrics["interrupted_actions"] += 1
        self._mark_lifecycle("batch_interrupted", action_id=action_id)

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

    def model_feedback(self, *, limit: int = 160, deferred: bool = False) -> str:
        """Return one bounded, highest-priority advisory for this action."""
        fresh_receipts = self.receipts[self._feedback_cursor :]
        self._feedback_cursor = len(self.receipts)
        visible: list[FeatureReceipt] = []
        for item in fresh_receipts:
            if not item.model_visible or not item.payload.get("message"):
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
            "submit_refusal": 0,
            "recovery": 1,
            "syntax_result": 2,
            "covering_red": 3,
            "signature_delta": 4,
        }
        selected = min(
            enumerate(visible),
            key=lambda item: (priority.get(item[1].feature_id, 10), item[0]),
        )[1]
        remaining_chars = self.max_guidance_chars - self._guidance_chars
        if self._guidance_events >= self.max_guidance_events or remaining_chars <= 0:
            self._guidance_suppressed += len(visible)
            return ""
        feedback = render_runtime_advisory(
            str(selected.payload["message"]), limit=min(limit, remaining_chars)
        )
        if not feedback:
            self._guidance_suppressed += len(visible)
            return ""
        self._guidance_suppressed += max(0, len(visible) - 1)
        self._guided_keys.add((selected.feature_id, selected.revision, ""))
        metadata = {
            "feature_id": selected.feature_id,
            "evidence_action": selected.action_id,
            "revision": selected.revision,
            "feedback": feedback,
        }
        if deferred:
            self._prepared_guidance = metadata
        else:
            self._record_guidance(metadata)
        return feedback
