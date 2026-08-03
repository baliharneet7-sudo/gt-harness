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

    def submit_decision(
        self, revision: str, *, sensor_healthy: bool = True
    ) -> SubmitDecision:
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
            command = (
                "command -v node >/dev/null 2>&1 || exit 0; "
                f"node --check -- {quoted}"
            )
        elif suffix in {"sh", "bash"}:
            command = f"command -v bash >/dev/null 2>&1 || exit 0; bash -n -- {quoted}"
        elif suffix == "rb":
            command = f"command -v ruby >/dev/null 2>&1 || exit 0; ruby -c -- {quoted}"
        elif suffix in {"cob", "cbl"}:
            command = (
                "command -v cobc >/dev/null 2>&1 || exit 0; "
                f"cobc -fsyntax-only -- {quoted}"
            )
        else:
            continue
        commands.append((path, command))
    return tuple(commands)
