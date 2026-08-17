"""Deterministic task-decisive fact derivation.

The persistent-state frame carries structural repository facts (a certified
related file, obligations, validation state).  Those facts describe the
repository; they do not name the concrete gap between the workspace state and
the task goal.  This module derives the task-decisive facts deterministically
from the three legal sources only:

1. the task instruction as provided to the agent,
2. the repository source and workspace bytes actually present in the task
   workspace, and
3. observed execution results (via the caller-supplied catalog of required
   checks and deliverables, which themselves derive from instruction and
   observed execution).

Derivation is a pure function of its inputs: identical inputs produce
identical facts, claims, and rendering.  No model call, no provider, no
grader-only artifact, and no host-side output is ever consulted.  Every
detector is bounded and instruction-anchored: a detector that cannot name a
concrete anchor abstains rather than fabricate.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from gt_engine.hybrid_retrieval import EvidenceOrigin

SCAN_MAX_FILES = 512
SCAN_MAX_HEAD_BYTES = 2048
SCAN_MAX_TEXT_CHARS = 4096
SCAN_MAX_DIR_DEPTH = 12
SCAN_MAX_INSTRUCTION_CHARS = 4000
DERIVATION_MAX_FACTS = 6
FACT_MAX_GAP_CHARS = 280
FACT_MAX_ANCHOR_PATHS = 6
SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        "target",
        ".extracted",
        "solution",
        "tests",
    }
)
_SKIP_FILE_NAMES = frozenset(
    {
        "reward" + ".txt",
        "ctrf" + ".json",
        "test_outputs" + ".py",
        "solution",
    }
)


class DecisiveKind(StrEnum):
    SECRET_LOCATION = "secret_location"
    BINARY_FORMAT = "binary_format"
    REQUIRED_CHECK = "required_check"
    PROJECT_CHECK = "project_check"
    DELIVERABLE_STATE = "deliverable_state"
    REPOSITORY_ANCHOR = "repository_anchor"


class DecisiveStatus(StrEnum):
    DERIVED = "derived"
    ABSTAINED = "abstained"


@dataclass(frozen=True, slots=True)
class WorkspaceEntry:
    """Bounded, deterministic view of one workspace file."""

    path: str
    size: int
    sha256: str
    head: bytes = b""
    text: str = ""
    origin: str = EvidenceOrigin.PREEXISTING_REPOSITORY.value

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
            "head_chars": min(len(self.head), 64),
            "text_chars": len(self.text),
            "origin": self.origin,
        }


@dataclass(frozen=True, slots=True)
class DecisiveFact:
    fact_id: str
    claim_id: str
    kind: DecisiveKind
    path: str
    gap_text: str
    detector: str
    line: int = 0
    source_revision: str = ""
    origin: str = EvidenceOrigin.PREEXISTING_REPOSITORY.value

    def as_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "claim_id": self.claim_id,
            "kind": self.kind.value,
            "path": self.path,
            "line": self.line,
            "gap_text": self.gap_text,
            "detector": self.detector,
            "source_revision": self.source_revision,
            "origin": self.origin,
        }


@dataclass(frozen=True, slots=True)
class DecisiveDerivation:
    status: DecisiveStatus
    facts: tuple[DecisiveFact, ...] = ()
    reason_codes: tuple[str, ...] = ()
    detectors: dict[str, int] = field(default_factory=dict)
    scan: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "facts": [fact.as_dict() for fact in self.facts],
            "reason_codes": list(self.reason_codes),
            "detectors": dict(self.detectors),
            "scan": dict(self.scan),
        }


def _abstain(*reasons: str) -> DecisiveDerivation:
    return DecisiveDerivation(
        status=DecisiveStatus.ABSTAINED,
        facts=(),
        reason_codes=tuple(dict.fromkeys(reasons)),
        detectors={},
        scan={},
    )


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "\0".join(str(part) for part in parts)
    return f"{prefix}-" + hashlib.sha256(payload.encode("utf-8", "surrogatepass")).hexdigest()[:20]


def _norm_path(path: str) -> str:
    normalized = str(path or "").replace("\\", "/")
    if normalized.startswith("/app/"):
        normalized = normalized[5:]
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def _bounded_text(text: str, limit: int) -> str:
    return str(text or "")[: max(0, int(limit))]


def build_workspace_scan(
    root: str,
    *,
    max_files: int = SCAN_MAX_FILES,
    max_head_bytes: int = SCAN_MAX_HEAD_BYTES,
    max_text_chars: int = SCAN_MAX_TEXT_CHARS,
    max_depth: int = SCAN_MAX_DIR_DEPTH,
) -> tuple[WorkspaceEntry, ...]:
    """Deterministic bounded walk of the task workspace.

    Only the task workspace (legal source 2) is read.  Entries are sorted by
    path so the walk is reproducible; counts and byte caps are fixed; binary
    head bytes and a bounded decoded text preview are captured per file.  A
    scan failure degrades to an empty tuple so the caller abstains rather
    than fabricate.
    """

    root_path = os.path.abspath(os.fspath(root or "."))
    if not os.path.isdir(root_path):
        return ()
    entries: list[WorkspaceEntry] = []

    def walk(directory: str, depth: int) -> None:
        if len(entries) >= max_files or depth > max_depth:
            return
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            return
        for name in names:
            if len(entries) >= max_files:
                return
            if name in SKIP_DIR_NAMES or name in _SKIP_FILE_NAMES:
                continue
            full = os.path.join(directory, name)
            relative = _norm_path(os.path.relpath(full, root_path))
            try:
                if os.path.isdir(full):
                    walk(full, depth + 1)
                    continue
                if not os.path.isfile(full):
                    continue
                size = os.path.getsize(full)
            except OSError:
                continue
            head = b""
            text = ""
            digest = hashlib.sha256()
            try:
                with open(full, "rb") as handle:
                    head = handle.read(max_head_bytes)
                    digest.update(head)
                    if size > max_head_bytes:
                        handle.seek(-min(max_head_bytes, size - max_head_bytes), os.SEEK_END)
                        digest.update(handle.read())
            except OSError:
                continue
            if _text_likely(head):
                text = _bounded_text(
                    head.decode("utf-8", "replace"),
                    max_text_chars,
                )
            entries.append(
                WorkspaceEntry(
                    path=relative,
                    size=int(size),
                    sha256=digest.hexdigest(),
                    head=head,
                    text=text,
                )
            )

    walk(root_path, 0)
    return tuple(entries)


def workspace_from_snapshot(
    entries: Mapping[str, Any],
    binary_heads: Mapping[str, bytes] | None = None,
    *,
    path_origins: Mapping[str, str] | None = None,
    max_files: int = SCAN_MAX_FILES,
    max_head_bytes: int = SCAN_MAX_HEAD_BYTES,
    max_text_chars: int = SCAN_MAX_TEXT_CHARS,
) -> tuple[WorkspaceEntry, ...]:
    """Deterministic bounded projection of the host-side sensor snapshot.

    The live Mini-SWE path runs inside a task container while the host process
    owns the sensor: ``central_runtime.WorkspaceSensor`` captures workspace
    metadata, digests, and bounded content through ``environment.exec`` (the
    same legal channel that builds the graph mirror).  The host filesystem
    never contains ``/app``, so a host-side ``os.listdir`` walk cannot be the
    live source of truth.  This pure function re-projects the already-legal
    in-container capture into the same ``WorkspaceEntry`` view the detectors
    consume.

    Entries are expected to expose ``kind``, ``size``, ``digest`` and optional
    ``content`` (the ``central_runtime.FileState`` shape).  Only regular files
    are admitted; skip rules mirror :func:`build_workspace_scan`; counts and
    byte caps are fixed; paths are normalized to workspace-relative form.
    ``binary_heads`` carries the bounded in-container head-byte capture for
    non-source candidates (also captured through the sensor channel), enabling
    the ``binary_format`` detector on the live path.
    """

    heads = {_norm_path(path): bytes(value or b"") for path, value in (binary_heads or {}).items()}
    origins = {
        _norm_path(path): str(value)
        for path, value in (path_origins or {}).items()
        if _norm_path(path)
    }
    valid_origins = frozenset(origin.value for origin in EvidenceOrigin)
    result: list[WorkspaceEntry] = []
    for path in sorted(entries):
        if len(result) >= max_files:
            break
        state = entries[path]
        if getattr(state, "kind", "") != "f":
            continue
        normalized = _norm_path(path)
        if not normalized:
            continue
        parts = normalized.split("/")
        if any(part in SKIP_DIR_NAMES for part in parts[:-1]):
            continue
        if parts[-1] in _SKIP_FILE_NAMES:
            continue
        content = getattr(state, "content", None)
        text = ""
        if isinstance(content, str) and content:
            text = _bounded_text(content, max_text_chars)
        result.append(
            WorkspaceEntry(
                path=normalized,
                size=int(getattr(state, "size", 0) or 0),
                sha256=str(getattr(state, "digest", "") or ""),
                head=heads.get(normalized, b"")[:max_head_bytes],
                text=text,
                origin=(
                    origins.get(normalized, EvidenceOrigin.PREEXISTING_REPOSITORY.value)
                    if origins.get(normalized) in valid_origins
                    else EvidenceOrigin.PREEXISTING_REPOSITORY.value
                ),
            )
        )
    return tuple(result)


def binary_interest(instruction: str) -> bool:
    """Instruction-anchored gate for bounded binary-head capture.

    Mirrors the ``binary_format`` detector's own interest test exactly (terms
    or path entities) so the sensor knows whether to spend one bounded
    in-container head capture.
    """

    return bool(_instruction_terms(instruction) & _BINARY_TERMS) or bool(
        _instruction_paths(instruction)
    )


_MAGIC_MIN = 8


def _text_likely(head: bytes) -> bool:
    sample = head[: _MAGIC_MIN]
    if not sample:
        return False
    if b"\x00" in sample and not sample.startswith(b"#!"):
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


_CREDENTIAL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("AWS_ACCESS_KEY_ID", r"\bAWS_ACCESS_KEY_ID\s*[:=]\s*(?:'|\")?[A-Z0-9]{16,40}"),
    ("AWS_SECRET_ACCESS_KEY", r"\bAWS_SECRET_ACCESS_KEY\s*[:=]\s*(?:'|\")?[A-Za-z0-9/+=]{16,80}"),
    ("GITHUB_TOKEN", r"\b(?:GITHUB|GH)_TOKEN\s*[:=]\s*(?:'|\")?[A-Za-z0-9_]{20,80}"),
    ("HUGGINGFACE_TOKEN", r"\b(?:HUGGING_FACE|HF)_TOKEN\s*[:=]\s*(?:'|\")?[A-Za-z0-9_]{10,80}"),
    ("GITLAB_TOKEN", r"\bGITLAB_TOKEN\s*[:=]\s*(?:'|\")?[A-Za-z0-9_\-]{10,80}"),
    ("SLACK_TOKEN", r"\bSLACK_TOKEN\s*[:=]\s*(?:'|\")?[A-Za-z0-9_\-]{10,80}"),
    ("OPENAI_API_KEY", r"\bOPENAI_API_KEY\s*[:=]\s*(?:'|\")?[A-Za-z0-9_\-]{10,80}"),
)

_BINARY_MAGICS: tuple[tuple[str, int, bytes, str], ...] = (
    ("ELF", 0, b"\x7fELF", "ELF"),
    ("PE", 0, b"MZ", "PE/COFF"),
    ("MACHO", 0, b"\xfe\xed\xfa\xce", "Mach-O"),
    ("MACHO_64", 0, b"\xfe\xed\xfa\xcf", "Mach-O 64-bit"),
    ("GZIP", 0, b"\x1f\x8b", "gzip"),
    ("ZIP", 0, b"PK\x03\x04", "ZIP archive"),
    ("TAR", 0, b"ustar", "tar archive"),
    ("BZIP2", 0, b"BZh", "bzip2"),
    ("XZ", 0, b"\xfd7zXZ", "xz"),
    ("PNG", 0, b"\x89PNG\r\n\x1a\n", "PNG image"),
    ("JPEG", 0, b"\xff\xd8\xff", "JPEG image"),
    ("PDF", 0, b"%PDF", "PDF"),
    ("MP4", 4, b"ftyp", "MP4/MOV video"),
    ("BMP", 0, b"BM", "BMP image"),
    ("NPY", 0, b"\x93NUMPY", "NumPy .npy array"),
    ("WASM", 0, b"\0asm", "WebAssembly binary"),
    ("SQLITE", 0, b"SQLite format 3\0", "SQLite database"),
    ("WAV", 0, b"RIFF", "RIFF/WAV container"),
    ("FLAC", 0, b"fLaC", "FLAC audio"),
    ("OGG", 0, b"OggS", "OGG container"),
)

_ELF_CLASS = {1: "32-bit", 2: "64-bit"}
_ELF_DATA = {1: "LSB", 2: "MSB"}
_ELF_MACHINE = {
    0x02: "SPARC",
    0x03: "x86",
    0x08: "MIPS",
    0x14: "PowerPC",
    0x16: "S390",
    0x28: "ARM",
    0x3E: "x86-64",
    0xB7: "AArch64",
    0xF3: "RISC-V",
}

_SECRET_TERMS = frozenset(
    {
        "secret",
        "credential",
        "credentials",
        "password",
        "token",
        "tokens",
        "api key",
        "api keys",
        "api_key",
        "private key",
        "access key",
        "access_key",
        "sanitize",
        "sanitization",
        "purge",
        "remove all",
    }
)
_BINARY_TERMS = frozenset(
    {
        "binary",
        "executable",
        "format",
        "elf",
        "pe ",
        "mach-o",
        "file type",
        "extract",
        "identify",
        "magic",
        "compiled",
        "machine code",
    }
)
_CHECK_TERMS = frozenset(
    {
        "validate",
        "validation",
        "test",
        "check",
        "run",
        "pytest",
        "verify",
        "verification",
    }
)
_DELIVERABLE_TERMS = frozenset(
    {
        "create",
        "produce",
        "generate",
        "write",
        "save",
        "output",
        "deliverable",
        "implement",
        "add",
        "new file",
    }
)

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PATH_ENTITY_RE = re.compile(r"(?<![\w./-])(?:\.{0,2}/)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.\-]+)+")


def _plausible_path(path: str) -> bool:
    """A path candidate from instruction prose is plausible only when it
    looks like a real file reference, not a sed expression, a shell
    redirect, or an arbitrary slash-containing phrase."""
    if not path:
        return False
    if path.startswith("/"):
        return True
    name = posixpath.basename(path.rstrip("/"))
    if not name:
        return False
    return "." in name


def _instruction_terms(instruction: str) -> frozenset[str]:
    head = _bounded_text(instruction, SCAN_MAX_INSTRUCTION_CHARS).lower()
    return frozenset(_TOKEN_RE.findall(head))


def _instruction_paths(instruction: str) -> tuple[str, ...]:
    head = (
        _bounded_text(instruction, SCAN_MAX_INSTRUCTION_CHARS)
        .replace("\\n", " ")
        .replace("\\t", " ")
    )
    seen: list[str] = []
    for raw in _PATH_ENTITY_RE.findall(head):
        path = _norm_path(raw.rstrip("."))
        if not path or len(path) > 160 or not _plausible_path(path):
            continue
        if path not in seen:
            seen.append(path)
        if len(seen) >= FACT_MAX_ANCHOR_PATHS:
            break
    return tuple(seen)


def _text_entries(
    workspace: tuple[WorkspaceEntry, ...],
) -> tuple[WorkspaceEntry, ...]:
    return tuple(entry for entry in workspace if entry.text)


def _secret_detector(
    instruction: str,
    workspace: tuple[WorkspaceEntry, ...],
    *,
    source_revision: str,
) -> list[DecisiveFact]:
    terms = _instruction_terms(instruction)
    if not (terms & _SECRET_TERMS):
        return []
    facts: list[DecisiveFact] = []
    for pattern_name, pattern in _CREDENTIAL_PATTERNS:
        regex = re.compile(pattern)
        hits: list[tuple[str, int, str]] = []
        for entry in _text_entries(workspace):
            for line_no, line in enumerate(entry.text.splitlines(), start=1):
                if regex.search(line):
                    hits.append((entry.path, line_no, entry.origin))
                    break
        if not hits:
            continue
        hit_path, hit_line, hit_origin = hits[0]
        gap = (
            f"Credential class {pattern_name} present in workspace "
            f"at {hit_path}:{hit_line} ({len(hits)} file(s) contaminated)."
        )
        facts.append(
            DecisiveFact(
                fact_id=_stable_id(
                    "decisive", DecisiveKind.SECRET_LOCATION.value, pattern_name, hit_path,
                    source_revision,
                ),
                claim_id=_stable_id(
                    "claim", "decisive", DecisiveKind.SECRET_LOCATION.value, pattern_name,
                    hit_path, hit_line,
                ),
                kind=DecisiveKind.SECRET_LOCATION,
                path=hit_path,
                line=hit_line,
                gap_text=_bounded_text(gap, FACT_MAX_GAP_CHARS),
                detector="secret_detector",
                source_revision=source_revision,
                origin=hit_origin,
            )
        )
        if len(facts) >= DERIVATION_MAX_FACTS:
            break
    return facts


def _elf_describe(head: bytes) -> str:
    if not head.startswith(b"\x7fELF"):
        return ""
    size = len(head)
    elf_class = _ELF_CLASS.get(head[4], "") if size > 5 else ""
    data = _ELF_DATA.get(head[5], "") if size > 6 else ""
    machine = _ELF_MACHINE.get(int.from_bytes(head[18:20], "little")) if size > 19 else ""
    parts = [part for part in ("ELF", elf_class, data, machine) if part]
    return " ".join(parts) if parts else "ELF"


def _binary_detector(
    instruction: str,
    workspace: tuple[WorkspaceEntry, ...],
    *,
    source_revision: str,
) -> list[DecisiveFact]:
    terms = _instruction_terms(instruction)
    path_entities = _instruction_paths(instruction)
    binary_interest = bool(terms & _BINARY_TERMS) or bool(path_entities)
    if not binary_interest:
        return []
    facts: list[DecisiveFact] = []
    for entry in workspace:
        if not entry.head or _text_likely(entry.head):
            continue
        if len(entry.head) < 4:
            continue
        kind = ""
        for _name, offset, magic, label in _BINARY_MAGICS:
            end = offset + len(magic)
            if end > len(entry.head):
                continue
            if entry.head[offset:end] == magic:
                kind = label
                break
        if not kind:
            continue
        if kind == "ELF":
            kind = _elf_describe(entry.head) or "ELF"
        gap = f"Binary {entry.path} is a {kind} file."
        facts.append(
            DecisiveFact(
                fact_id=_stable_id(
                    "decisive", DecisiveKind.BINARY_FORMAT.value, entry.path, kind, source_revision
                ),
                claim_id=_stable_id(
                    "claim", "decisive", DecisiveKind.BINARY_FORMAT.value, entry.path, kind
                ),
                kind=DecisiveKind.BINARY_FORMAT,
                path=entry.path,
                gap_text=_bounded_text(gap, FACT_MAX_GAP_CHARS),
                detector="binary_format_detector",
                source_revision=source_revision,
                origin=entry.origin,
            )
        )
        if len(facts) >= DERIVATION_MAX_FACTS:
            break
    return facts


def _required_check_detector(
    instruction: str,
    validation_commands: tuple[str, ...],
    *,
    source_revision: str,
) -> list[DecisiveFact]:
    terms = _instruction_terms(instruction)
    if not (terms & _CHECK_TERMS) and not validation_commands:
        return []
    facts: list[DecisiveFact] = []
    for command in validation_commands:
        clean = _bounded_text(command, 240).strip()
        if not clean:
            continue
        gap = f"Required validation command: {clean}"
        facts.append(
            DecisiveFact(
                fact_id=_stable_id(
                    "decisive", DecisiveKind.REQUIRED_CHECK.value, clean, source_revision
                ),
                claim_id=_stable_id("claim", "decisive", DecisiveKind.REQUIRED_CHECK.value, clean),
                kind=DecisiveKind.REQUIRED_CHECK,
                path="",
                gap_text=_bounded_text(gap, FACT_MAX_GAP_CHARS),
                detector="required_check_detector",
                source_revision=source_revision,
                origin=EvidenceOrigin.EXTERNAL_RUNTIME.value,
            )
        )
        if len(facts) >= DERIVATION_MAX_FACTS:
            break
    return facts


def _deliverable_detector(
    instruction: str,
    workspace: tuple[WorkspaceEntry, ...],
    deliverables: tuple[str, ...],
    *,
    source_revision: str,
) -> list[DecisiveFact]:
    terms = _instruction_terms(instruction)
    if not (terms & _DELIVERABLE_TERMS) and not deliverables:
        return []
    workspace_paths = frozenset(entry.path for entry in workspace)
    facts: list[DecisiveFact] = []
    for deliverable in deliverables:
        path = _norm_path(deliverable)
        if not path or len(path) > 200:
            continue
        present = path in workspace_paths or any(
            wp == path or wp.endswith("/" + path) for wp in workspace_paths
        )
        if present:
            gap = f"Required deliverable {path} is present in the workspace."
        else:
            gap = f"Required deliverable {path} is absent in the workspace."
        facts.append(
            DecisiveFact(
                fact_id=_stable_id(
                    "decisive", DecisiveKind.DELIVERABLE_STATE.value, path, source_revision
                ),
                claim_id=_stable_id(
                    "claim",
                    "decisive",
                    DecisiveKind.DELIVERABLE_STATE.value,
                    path,
                    "present" if present else "absent",
                ),
                kind=DecisiveKind.DELIVERABLE_STATE,
                path=path,
                gap_text=_bounded_text(gap, FACT_MAX_GAP_CHARS),
                detector="deliverable_detector",
                source_revision=source_revision,
                origin=EvidenceOrigin.TASK_DELIVERABLE.value,
            )
        )
        if len(facts) >= DERIVATION_MAX_FACTS:
            break
    return facts


def _structural_anchor_detector(
    workspace: tuple[WorkspaceEntry, ...],
    focus_anchors: tuple[str, ...],
    *,
    source_revision: str,
) -> list[DecisiveFact]:
    """Emit a bounded certified repository anchor as a fallback decisive fact.

    This guarantees the decisive frame is never empty on a healthy workspace:
    when no detector can name a concrete task gap, the top certified catalog
    focus anchor (a graph-derived ``path:line#symbol``) is still decision-relevant
    grounded context.  It never fabricates a relationship and never references a
    grader-only artifact.
    """

    if not focus_anchors:
        return []
    workspace_paths = {entry.path for entry in workspace}
    workspace_origins = {entry.path: entry.origin for entry in workspace}
    facts: list[DecisiveFact] = []
    for anchor in focus_anchors:
        clean = _bounded_text(str(anchor or ""), 240).strip()
        if not clean:
            continue
        path_part = clean.split("#", 1)[0].rsplit(":", 1)[0].strip()
        if not path_part:
            continue
        if not (
            path_part in workspace_paths
            or any(path_part in entry_path for entry_path in workspace_paths)
            or any(entry_path.endswith("/" + path_part) for entry_path in workspace_paths)
        ):
            continue
        gap = f"Certified repository anchor: {clean}."
        facts.append(
            DecisiveFact(
                fact_id=_stable_id(
                    "decisive", DecisiveKind.REPOSITORY_ANCHOR.value, clean, source_revision
                ),
                claim_id=_stable_id(
                    "claim", "decisive", DecisiveKind.REPOSITORY_ANCHOR.value, clean
                ),
                kind=DecisiveKind.REPOSITORY_ANCHOR,
                path=path_part,
                gap_text=_bounded_text(gap, FACT_MAX_GAP_CHARS),
                detector="structural_anchor_detector",
                source_revision=source_revision,
                origin=workspace_origins.get(
                    path_part, EvidenceOrigin.PREEXISTING_REPOSITORY.value
                ),
            )
        )
        if len(facts) >= DERIVATION_MAX_FACTS:
            break
    return facts


def _project_check_detector(
    project_checks: tuple[str, ...],
    *,
    source_revision: str,
) -> list[DecisiveFact]:
    """Emit discovered repository-contract validation candidates.

    ``evidence.project_checks`` (Makefile test targets, pytest config, npm
    scripts, Cargo/Go modules) are discovered from the repository source that is
    actually present in the workspace -- legal source 2.  They are advisory
    candidates, never ``required``; the wording and kind reflect that.
    """

    facts: list[DecisiveFact] = []
    for command in project_checks:
        clean = _bounded_text(str(command or ""), 240).strip()
        if not clean:
            continue
        gap = f"Project validation candidate: {clean}"
        facts.append(
            DecisiveFact(
                fact_id=_stable_id(
                    "decisive", DecisiveKind.PROJECT_CHECK.value, clean, source_revision
                ),
                claim_id=_stable_id(
                    "claim", "decisive", DecisiveKind.PROJECT_CHECK.value, clean
                ),
                kind=DecisiveKind.PROJECT_CHECK,
                path="",
                gap_text=_bounded_text(gap, FACT_MAX_GAP_CHARS),
                detector="project_check_detector",
                source_revision=source_revision,
                origin=EvidenceOrigin.PREEXISTING_REPOSITORY.value,
            )
        )
        if len(facts) >= DERIVATION_MAX_FACTS:
            break
    return facts


def derive_decisive_facts(
    *,
    instruction: str,
    workspace: tuple[WorkspaceEntry, ...],
    validation_commands: tuple[str, ...] = (),
    deliverables: tuple[str, ...] = (),
    project_checks: tuple[str, ...] = (),
    focus_anchors: tuple[str, ...] = (),
    source_revision: str = "",
    allow_empty_workspace: bool = False,
) -> DecisiveDerivation:
    """Derive bounded task-decisive facts from the three legal sources only.

    Deterministic by construction: every detector is a pure function of the
    instruction text, the workspace entries, and the caller-provided catalog
    rows.  A missing instruction abstains.  The legacy decisive caller also
    abstains on an empty workspace; the universal semantic substrate may
    explicitly allow it so instruction-owned deliverables and checks are
    still derived for genuinely source-less tasks.
    """

    instruction = str(instruction or "")
    if not instruction.strip():
        return _abstain("instruction_empty")
    workspace = tuple(workspace)
    if not workspace and not allow_empty_workspace:
        return _abstain("workspace_scan_empty")

    detector_calls: dict[str, int] = {}
    collected: list[DecisiveFact] = []

    def run(name: str, detector: Any) -> None:
        detector_calls[name] = detector_calls.get(name, 0) + 1
        try:
            facts = detector()
        except Exception:  # noqa: BLE001 - a detector failure must abstain, not crash
            return
        for fact in facts:
            if len(collected) >= DERIVATION_MAX_FACTS:
                return
            if any(existing.fact_id == fact.fact_id for existing in collected):
                continue
            collected.append(fact)

    run(
        "secret_detector",
        lambda: _secret_detector(instruction, workspace, source_revision=source_revision),
    )
    run(
        "binary_format_detector",
        lambda: _binary_detector(instruction, workspace, source_revision=source_revision),
    )
    run(
        "required_check_detector",
        lambda: _required_check_detector(
            instruction, tuple(validation_commands), source_revision=source_revision
        ),
    )
    run(
        "project_check_detector",
        lambda: _project_check_detector(tuple(project_checks), source_revision=source_revision),
    )
    run(
        "deliverable_detector",
        lambda: _deliverable_detector(
            instruction, workspace, tuple(deliverables), source_revision=source_revision
        ),
    )
    if not collected:
        run(
            "structural_anchor_detector",
            lambda: _structural_anchor_detector(
                workspace, tuple(focus_anchors), source_revision=source_revision
            ),
        )

    if not collected:
        return DecisiveDerivation(
            status=DecisiveStatus.ABSTAINED,
            facts=(),
            reason_codes=("no_instruction_anchored_decisive_fact",),
            detectors=detector_calls,
            scan={
                "entries": len(workspace),
                "text_entries": len(_text_entries(workspace)),
            },
        )
    return DecisiveDerivation(
        status=DecisiveStatus.DERIVED,
        facts=tuple(collected),
        reason_codes=(),
        detectors=detector_calls,
        scan={
            "entries": len(workspace),
            "text_entries": len(_text_entries(workspace)),
        },
    )
