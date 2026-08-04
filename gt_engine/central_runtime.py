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

_MANIFEST_COMMAND = (
    "set -o pipefail; LC_ALL=C find . -xdev -mindepth 1 "
    "-printf '%y\\t%s\\t%T@\\t%C@\\t%P\\t%l\\n' 2>/dev/null "
    "| LC_ALL=C sort | head -n 50001"
)
_PRIVATE_TERMS = re.compile(r"groundtruth|gt_[a-z0-9_]*", re.IGNORECASE)
_CHECK_WORDS = re.compile(
    r"(?:^|[;&|()\s/])(?:pytest|test|tests|check|verify|unittest|ctest|"
    r"mvn\s+test|gradle\s+test|npm\s+test|cargo\s+test|go\s+test)(?:$|\s)",
    re.IGNORECASE,
)
_SUBMIT_MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"


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
    "GT_CHANGE_SURFACE": "search_result",
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
        "covering_red": ("check_failed",),
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


def is_check_command(command: str) -> bool:
    return bool(_CHECK_WORDS.search(normalize_command(command)))


def explicit_check_commands(instruction: str) -> tuple[str, ...]:
    checks = []
    for candidate in re.findall(r"`([^`\r\n]+)`", instruction):
        if is_check_command(candidate) and not is_submit_command(candidate):
            checks.append(normalize_command(candidate))
    return tuple(dict.fromkeys(checks))


def is_grounded_check(command: str, explicit_checks: Iterable[str]) -> bool:
    normalized = normalize_command(command)
    return any(check == normalized or check in normalized for check in explicit_checks)


@dataclass(slots=True)
class EvidenceLedger:
    """Fresh deterministic evidence with bounded, fail-open submit holds."""

    max_holds: int = 1
    checks: dict[str, CheckEvidence] = field(default_factory=dict)
    _holds: dict[tuple[str, tuple[str, ...]], int] = field(default_factory=dict)

    def record_check(
        self,
        command: str,
        *,
        returncode: int,
        revision: str,
        grounded: bool,
    ) -> None:
        key = normalize_command(command)
        if returncode == 0:
            self.checks.pop(key, None)
            return
        self.checks[key] = CheckEvidence(key, returncode, revision, grounded)

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


def render_runtime_feedback(detail: str, *, limit: int = 320) -> str:
    """Render concise model feedback without exposing private implementation names."""
    cleaned = _PRIVATE_TERMS.sub("runtime", " ".join(detail.split()))
    prefix = "Runtime check: "
    suffix = " Submit again to continue without another hold."
    available = max(0, limit - len(prefix) - len(suffix))
    if len(cleaned) > available:
        cleaned = cleaned[: max(0, available - 3)].rstrip() + "..."
    return (prefix + cleaned + suffix)[:limit]


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

    def __init__(self, *, enabled: bool = True, model_visible: bool = False) -> None:
        self.enabled = enabled
        self.model_visible = model_visible
        self.receipts: list[FeatureReceipt] = []
        self._seen: set[tuple[str, int, str]] = set()
        self._failed_actions: dict[tuple[str, int], int] = {}
        self._searched = False
        self._feedback_cursor = 0
        self._guidance_events = 0
        self._guidance_chars = 0
        self._guidance_features: list[str] = []

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
                model_visible=self.model_visible,
            )
        )
        # CAP_OWNER delivery is a separate auditable row, not an alias that
        # inflates the FACT count.
        for cap_id, owner in CENTRAL_CAP_OWNERS.items():
            if cap_id == "GT_CERT_DELIVERY":
                # Delivery is emitted at the submit boundary with its own
                # sensor/refusal payload, not as a submit-refusal alias.
                continue
            if owner == feature_id:
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
                )

    @staticmethod
    def _payload(feature_id: str, boundary: str, reason: str) -> dict[str, Any]:
        messages = {
            "caller_contract": "Inspect the verified callers before changing this callable.",
            "covering_red": "A required check is failing; repair the attributable regression.",
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

    def begin_task(self, instruction: str, *, revision: str) -> None:
        if not self.enabled:
            return
        if instruction.strip():
            self._emit(
                "obligations",
                boundary="task_start",
                action_id=0,
                revision=revision,
                reason="non_empty_task_instruction",
                payload={
                    "requirements_present": True,
                    "message": self._payload(
                        "obligations", "task_start", "non_empty_task_instruction"
                    )["message"],
                },
            )

    def observe_action(
        self,
        *,
        action_id: int,
        command: str,
        output: str,
        returncode: int,
        transition: WorkspaceTransition,
        revision: str,
    ) -> None:
        if not self.enabled:
            return
        normalized = normalize_command(command)
        text = f"{normalized} {output or ''}"
        is_search = bool(self._SEARCH.search(normalized))
        if is_search and output.strip():
            self._searched = True
            self._emit(
                "localization",
                boundary="search_result",
                action_id=action_id,
                revision=revision,
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
                self._emit(
                    "caller_contract",
                    boundary="search_result",
                    action_id=action_id,
                    revision=revision,
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
                self._emit(
                    "newfile_precedent",
                    boundary="search_result",
                    action_id=action_id,
                    revision=revision,
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

        if returncode != 0 and (is_check_command(normalized) or self._FAILURE.search(output)):
            self._emit(
                "covering_red",
                boundary="test_result",
                action_id=action_id,
                revision=revision,
                reason="failed_check_or_failure_output",
                payload={
                    "check_failed": True,
                    "returncode": returncode,
                    "message": self._payload(
                        "covering_red", "test_result", "failed_check_or_failure_output"
                    )["message"],
                },
            )
            failure_key = (normalized, returncode)
            count = self._failed_actions.get(failure_key, 0) + 1
            self._failed_actions[failure_key] = count
            if count >= 2:
                self._emit(
                    "recovery",
                    boundary="test_result",
                    action_id=action_id,
                    revision=revision,
                    reason="same_failure_repeated",
                    payload={
                        "repeat_count": count,
                        "message": self._payload(
                            "recovery", "test_result", "same_failure_repeated"
                        )["message"],
                    },
                )

        if transition.created and (self._searched or self._PRECEDENT.search(text)):
            self._emit(
                "newfile_precedent",
                boundary="edit_result",
                action_id=action_id,
                revision=revision,
                reason="new_file_after_search_or_precedent",
                payload={
                    "created_files": len(transition.created),
                    "message": self._payload(
                        "newfile_precedent", "edit_result", "new_file_after_search_or_precedent"
                    )["message"],
                },
            )

        if (
            transition.changed_paths
            and self._EDIT.search(normalized)
            and self._SIGNATURE.search(text)
        ):
            self._emit(
                "signature_delta",
                boundary="edit_result",
                action_id=action_id,
                revision=revision,
                reason="signature-shaped edit on changed path",
                payload={
                    "changed_paths": list(transition.changed_paths),
                    "signature_edit": True,
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
    ) -> None:
        self._emit(
            "syntax_result",
            boundary="edit_result",
            action_id=action_id,
            revision=revision,
            decision="DELIVERED" if failed else "PASS",
            reason=reason,
            payload={
                "ok": not failed,
                "fresh": True,
                "message": self._payload("syntax_result", "edit_result", reason)["message"],
            },
        )

    def record_submit(
        self,
        *,
        action_id: int,
        revision: str,
        refused: bool,
        sensor_healthy: bool,
    ) -> None:
        if refused:
            self._emit(
                "submit_refusal",
                boundary="submit",
                action_id=action_id,
                revision=revision,
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
            decision="DELIVERED" if sensor_healthy else "PASS",
            reason="submission_readiness_receipt",
            payload={
                "sensor_healthy": sensor_healthy,
                "refused": refused,
                "message": "Submission readiness was evaluated at the current workspace revision.",
            },
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
            "delivered_counts": by_feature,
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
                }
                for item in self.receipts
            ],
        }

    def model_feedback(self, *, limit: int = 320) -> str:
        """Return one bounded, highest-priority advisory for this action."""
        visible = [
            item
            for item in self.receipts[self._feedback_cursor :]
            if item.model_visible and item.payload.get("message")
        ]
        self._feedback_cursor = len(self.receipts)
        if not visible:
            return ""
        priority = {
            "submit_refusal": 0,
            "recovery": 1,
            "syntax_result": 2,
            "covering_red": 3,
            "signature_delta": 4,
            "caller_contract": 5,
            "newfile_precedent": 6,
            "def_partition": 7,
            "localization": 8,
            "obligations": 9,
        }
        selected = min(
            enumerate(visible),
            key=lambda item: (priority.get(item[1].feature_id, 10), item[0]),
        )[1]
        feedback = render_runtime_feedback(str(selected.payload["message"]), limit=limit)
        self._guidance_events += 1
        self._guidance_chars += len(feedback)
        self._guidance_features.append(selected.feature_id)
        return feedback
