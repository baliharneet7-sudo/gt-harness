"""Canonical repository graph lifecycle and query boundary.

Every product surface uses this service.  A SQLite file is never evidence by
itself: graph-derived answers are released only through a receipt bound to the
current Git commit, graph-input content revision, schema, and database digest.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from gt_engine.graph_inputs import is_graph_input, is_graph_metadata
from gt_engine.indexer import ensure_index_with_receipt, refresh_index_files
from gt_harness.indexer_setup import GT_INDEX_BUILD_ID

GRAPH_BUILDER_VERSION = f"gt-index-{GT_INDEX_BUILD_ID}"
GRAPH_RECEIPT_SCHEMA = "gt.graph_receipt.v2"
CANONICAL_QUERY_MODES = (
    "definition",
    "callers",
    "callees",
    "imports",
    "importers",
    "implementations",
    "subclasses",
    "references",
    "impact",
    "tests",
    "search",
)
QUERY_MODE_ALIASES = {
    "definitions": "definition",
    "caller": "callers",
    "callee": "callees",
    "import": "imports",
    "importer": "importers",
    "implementation": "implementations",
    "subclass": "subclasses",
    "reference": "references",
    "test": "tests",
    "refs": "references",
}
SUPPORTED_QUERY_MODES = tuple((*CANONICAL_QUERY_MODES, *QUERY_MODE_ALIASES))
_READY = frozenset({"READY", "READY_WITH_DECLARED_LIMITATIONS"})
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".gt",
        ".groundtruth",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        "target",
    }
)


class GraphStatus(StrEnum):
    ABSENT = "ABSENT"
    BUILDING = "BUILDING"
    READY = "READY"
    READY_WITH_DECLARED_LIMITATIONS = "READY_WITH_DECLARED_LIMITATIONS"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    STALE = "STALE"


class GraphNotReadyError(RuntimeError):
    """Raised when a caller attempts to query an uncertified graph."""


@dataclass(frozen=True, slots=True)
class RepositoryIdentity:
    repository: str
    commit_sha: str
    branch: str
    working_tree_state: str
    source_revision: str
    files_discovered: int
    graph_input_files: int
    source_bytes: int
    graph_input_hashes: dict[str, str]


@dataclass(frozen=True, slots=True)
class GraphReceipt:
    repository: str
    commit_sha: str
    branch: str
    working_tree_state: str
    source_revision: str
    graph_schema_version: str
    graph_builder_version: str
    build_started: str
    build_completed: str
    build_status: GraphStatus
    files_discovered: int
    files_attempted: int
    files_indexed: int
    files_skipped: int
    files_failed: int
    symbols: int
    nodes_by_type: dict[str, int]
    edges_by_type: dict[str, int]
    coverage: float
    build_duration_ms: float
    persistent_graph_path: str
    graph_checksum_or_identity: str
    query_ready: bool
    degraded_reasons: tuple[str, ...]
    repository_files_discovered: int = 0
    discovery_method: str = ""
    skipped_reasons: dict[str, int] = field(default_factory=dict)
    skipped_paths: tuple[dict[str, str], ...] = ()
    failed_paths: tuple[str, ...] = ()
    excluded_directories: tuple[dict[str, str], ...] = ()
    graph_input_hashes: dict[str, str] = field(default_factory=dict)
    update_mode: str = ""
    parser_runtime: str = "gt-index/tree-sitter"
    graph_bytes: int = 0
    source_bytes: int = 0
    receipt_schema: str = GRAPH_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.query_ready != (self.build_status.value in _READY):
            raise ValueError("query_ready must exactly match a READY graph status")
        if self.query_ready and (
            not self.commit_sha
            or not self.source_revision
            or not self.persistent_graph_path
            or not self.graph_checksum_or_identity
        ):
            raise ValueError("a READY receipt requires repository and graph identities")
        if not 0.0 <= float(self.coverage) <= 1.0:
            raise ValueError("coverage must be between zero and one")

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["build_status"] = self.build_status.value
        value["degraded_reasons"] = list(self.degraded_reasons)
        value["skipped_paths"] = list(self.skipped_paths)
        value["failed_paths"] = list(self.failed_paths)
        value["excluded_directories"] = list(self.excluded_directories)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GraphReceipt:
        row = dict(value)
        if row.get("receipt_schema", GRAPH_RECEIPT_SCHEMA) != GRAPH_RECEIPT_SCHEMA:
            raise ValueError("unsupported graph receipt schema")
        row["build_status"] = GraphStatus(str(row["build_status"]))
        row["degraded_reasons"] = tuple(str(item) for item in row.get("degraded_reasons", ()))
        row["skipped_reasons"] = {
            str(key): int(count) for key, count in dict(row.get("skipped_reasons", {})).items()
        }
        row["skipped_paths"] = tuple(
            {"path": str(item.get("path", "")), "reason": str(item.get("reason", ""))}
            for item in row.get("skipped_paths", ())
            if isinstance(item, dict)
        )
        row["failed_paths"] = tuple(str(item) for item in row.get("failed_paths", ()))
        row["excluded_directories"] = tuple(
            {"path": str(item.get("path", "")), "reason": str(item.get("reason", ""))}
            for item in row.get("excluded_directories", ())
            if isinstance(item, dict)
        )
        row["graph_input_hashes"] = {
            str(path): str(digest)
            for path, digest in dict(row.get("graph_input_hashes", {})).items()
        }
        row["nodes_by_type"] = {
            str(key): int(count) for key, count in dict(row.get("nodes_by_type", {})).items()
        }
        row["edges_by_type"] = {
            str(key): int(count) for key, count in dict(row.get("edges_by_type", {})).items()
        }
        return cls(**row)


@dataclass(frozen=True, slots=True)
class _GraphBuildStats:
    schema: str
    symbols: int
    nodes: dict[str, int]
    edges: dict[str, int]
    files_attempted: int
    files_parsed: int
    file_hashes: int
    parse_failures: int
    file_hash_failures: int
    files_discovered: int
    skipped_count: int
    discovery_method: str
    skipped_reasons: dict[str, int]
    skipped_paths: tuple[dict[str, str], ...]
    parse_failure_details: tuple[str, ...]
    file_hash_failure_details: tuple[str, ...]
    excluded_directories: tuple[dict[str, str], ...]
    receipt_complete: bool


def _run_git(root: Path, *args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return int(result.returncode), result.stdout.strip()


def _repository_root(root: str | os.PathLike[str]) -> Path:
    candidate = Path(root).resolve()
    code, top = _run_git(candidate, "rev-parse", "--show-toplevel")
    return Path(top).resolve() if code == 0 and top else candidate


def _iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in _SKIP_DIRS)
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            if path.is_file() or path.is_symlink():
                yield path


def compute_repository_identity(root: str | os.PathLike[str]) -> RepositoryIdentity:
    """Hash the actual graph inputs, including modified and untracked files."""

    repository = _repository_root(root)
    code, commit = _run_git(repository, "rev-parse", "HEAD")
    commit_sha = commit if code == 0 else "NO_COMMIT"
    code, branch = _run_git(repository, "symbolic-ref", "--short", "-q", "HEAD")
    branch_name = branch if code == 0 and branch else "DETACHED"
    status_code, status = _run_git(
        repository, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"
    )
    working_tree_state = "dirty" if status_code == 0 and status else "clean"
    if status_code != 0:
        working_tree_state = "not_git"

    framed: list[tuple[str, bytes]] = []
    files_discovered = 0
    source_bytes = 0
    graph_input_hashes: dict[str, str] = {}
    for path in _iter_files(repository):
        files_discovered += 1
        relative = path.relative_to(repository).as_posix()
        try:
            if path.is_symlink():
                payload = ("SYMLINK\0" + os.readlink(path)).encode("utf-8", "surrogatepass")
            else:
                payload = path.read_bytes()
        except OSError as exc:
            payload = f"UNREADABLE\0{type(exc).__name__}".encode()
        prefix = payload[:65_536]
        if relative == ".gitmodules" or is_graph_input(relative, prefix):
            framed.append((relative, payload))
            graph_input_hashes[relative] = hashlib.sha256(payload).hexdigest()
            source_bytes += len(payload)

    _, submodules = _run_git(repository, "submodule", "status", "--recursive")
    digest = hashlib.sha256()
    for value in (commit_sha, submodules):
        encoded = value.encode("utf-8", "surrogatepass")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    for relative, payload in sorted(framed):
        name = relative.encode("utf-8", "surrogatepass")
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return RepositoryIdentity(
        repository=str(repository),
        commit_sha=commit_sha,
        branch=branch_name,
        working_tree_state=working_tree_state,
        source_revision=digest.hexdigest(),
        files_discovered=files_discovered,
        graph_input_files=len(framed),
        source_bytes=source_bytes,
        graph_input_hashes=graph_input_hashes,
    )


class RepositoryGraphService:
    """Build, reopen, certify, and query the one canonical graph database."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        state_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self.root = _repository_root(root)
        self.state_dir = (
            Path(state_dir).resolve() if state_dir is not None else self.root / ".groundtruth"
        )
        self.graph_path = self.state_dir / "graph.db"
        self.receipt_path = self.state_dir / "graph-receipt.json"

    @staticmethod
    def file_sha256(path: str | os.PathLike[str]) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _write_receipt(self, receipt: GraphReceipt) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(receipt.as_dict(), ensure_ascii=False, sort_keys=True, indent=2).encode(
                "utf-8"
            )
            + b"\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=self.state_dir, prefix=".graph-receipt.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.receipt_path)

    def _empty_receipt(
        self,
        status: GraphStatus,
        identity: RepositoryIdentity,
        *reasons: str,
    ) -> GraphReceipt:
        return GraphReceipt(
            repository=identity.repository,
            commit_sha=identity.commit_sha,
            branch=identity.branch,
            working_tree_state=identity.working_tree_state,
            source_revision=identity.source_revision,
            graph_schema_version="",
            graph_builder_version=GRAPH_BUILDER_VERSION,
            build_started="",
            build_completed="",
            build_status=status,
            files_discovered=identity.files_discovered,
            files_attempted=0,
            files_indexed=0,
            files_skipped=0,
            files_failed=0,
            symbols=0,
            nodes_by_type={},
            edges_by_type={},
            coverage=0.0,
            build_duration_ms=0.0,
            persistent_graph_path=str(self.graph_path) if self.graph_path.exists() else "",
            graph_checksum_or_identity="",
            query_ready=False,
            degraded_reasons=tuple(dict.fromkeys(reasons)),
            repository_files_discovered=identity.files_discovered,
            graph_input_hashes=identity.graph_input_hashes,
            source_bytes=identity.source_bytes,
        )

    def status(self) -> GraphReceipt:
        current = compute_repository_identity(self.root)
        if not self.receipt_path.is_file():
            state = GraphStatus.FAILED if self.graph_path.exists() else GraphStatus.ABSENT
            reason = "graph_receipt_missing" if self.graph_path.exists() else "graph_not_built"
            return self._empty_receipt(state, current, reason)
        try:
            stored = GraphReceipt.from_dict(
                json.loads(self.receipt_path.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return self._empty_receipt(GraphStatus.FAILED, current, "graph_receipt_invalid")

        stale: list[str] = []
        if Path(stored.repository).resolve() != self.root:
            stale.append("repository_root_mismatch")
        if stored.commit_sha != current.commit_sha:
            stale.append("commit_sha_mismatch")
        if stored.source_revision != current.source_revision:
            stale.append("source_revision_mismatch")
        if stored.graph_builder_version != GRAPH_BUILDER_VERSION:
            stale.append("graph_builder_version_mismatch")
        if stale:
            return replace(
                stored,
                branch=current.branch,
                working_tree_state=current.working_tree_state,
                build_status=GraphStatus.STALE,
                query_ready=False,
                degraded_reasons=tuple(dict.fromkeys((*stored.degraded_reasons, *stale))),
            )
        graph = Path(stored.persistent_graph_path)
        if not graph.is_file():
            return replace(
                stored,
                build_status=GraphStatus.FAILED,
                query_ready=False,
                degraded_reasons=tuple(
                    dict.fromkeys((*stored.degraded_reasons, "graph_database_missing"))
                ),
            )
        try:
            checksum = self.file_sha256(graph)
        except OSError:
            checksum = ""
        if checksum != stored.graph_checksum_or_identity:
            return replace(
                stored,
                build_status=GraphStatus.FAILED,
                query_ready=False,
                degraded_reasons=tuple(
                    dict.fromkeys((*stored.degraded_reasons, "graph_checksum_mismatch"))
                ),
            )
        try:
            connection = sqlite3.connect(f"file:{graph.as_posix()}?mode=ro", uri=True)
            try:
                quick = str(connection.execute("PRAGMA quick_check").fetchone()[0]).lower()
                connection.execute("SELECT 1 FROM nodes LIMIT 1").fetchall()
                connection.execute("SELECT 1 FROM edges LIMIT 1").fetchall()
            finally:
                connection.close()
        except (sqlite3.Error, OSError):
            quick = "error"
        if quick != "ok":
            return replace(
                stored,
                build_status=GraphStatus.FAILED,
                query_ready=False,
                degraded_reasons=tuple(
                    dict.fromkeys((*stored.degraded_reasons, "graph_integrity_failed"))
                ),
            )
        return stored

    @staticmethod
    def _graph_stats(graph: Path) -> _GraphBuildStats:
        connection = sqlite3.connect(f"file:{graph.as_posix()}?mode=ro", uri=True)
        try:
            metadata = {
                str(key): str(value)
                for key, value in connection.execute("SELECT key,value FROM project_meta")
            }

            def integer(key: str, default: int = -1) -> int:
                try:
                    return int(metadata.get(key, default))
                except (TypeError, ValueError):
                    return default

            def json_list(key: str) -> tuple[Any, ...]:
                try:
                    value = json.loads(metadata.get(key, "[]"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    return ()
                return tuple(value) if isinstance(value, list) else ()

            nodes = {
                str(label or "UNKNOWN"): int(count)
                for label, count in connection.execute(
                    "SELECT label,COUNT(*) FROM nodes GROUP BY label ORDER BY label"
                )
            }
            edges = {
                str(kind or "UNKNOWN"): int(count)
                for kind, count in connection.execute(
                    "SELECT type,COUNT(*) FROM edges GROUP BY type ORDER BY type"
                )
            }
            try:
                skipped_reasons_value = json.loads(metadata.get("discovery_skipped_reasons", "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                skipped_reasons_value = {}
            skipped_reasons = (
                {
                    str(key): int(value)
                    for key, value in skipped_reasons_value.items()
                    if isinstance(value, int) and value >= 0
                }
                if isinstance(skipped_reasons_value, dict)
                else {}
            )

            def records(key: str) -> tuple[dict[str, str], ...]:
                return tuple(
                    {"path": str(item.get("path", "")), "reason": str(item.get("reason", ""))}
                    for item in json_list(key)
                    if isinstance(item, dict)
                )

            required = {
                "files_parsed",
                "parse_failure_details",
                "discovery_method",
                "discovery_files_seen",
                "discovery_skipped_count",
                "discovery_skipped_reasons",
                "discovery_skipped_paths",
                "discovery_skipped_directories",
                "file_hash_failures",
                "file_hash_failure_details",
            }
            file_nodes = sum(count for label, count in nodes.items() if label.casefold() == "file")
            return _GraphBuildStats(
                schema=metadata.get("schema_version", ""),
                symbols=max(0, sum(nodes.values()) - file_nodes),
                nodes=nodes,
                edges=edges,
                files_attempted=integer("file_count"),
                files_parsed=integer("files_parsed"),
                file_hashes=int(
                    connection.execute("SELECT COUNT(*) FROM file_hashes").fetchone()[0]
                ),
                parse_failures=integer("parse_failures"),
                file_hash_failures=integer("file_hash_failures"),
                files_discovered=integer("discovery_files_seen"),
                skipped_count=integer("discovery_skipped_count"),
                discovery_method=metadata.get("discovery_method", ""),
                skipped_reasons=skipped_reasons,
                skipped_paths=records("discovery_skipped_paths"),
                parse_failure_details=tuple(
                    str(item) for item in json_list("parse_failure_details")
                ),
                file_hash_failure_details=tuple(
                    str(item) for item in json_list("file_hash_failure_details")
                ),
                excluded_directories=records("discovery_skipped_directories"),
                receipt_complete=required <= metadata.keys(),
            )
        finally:
            connection.close()

    def _finalize_graph_receipt(
        self,
        index: Any,
        before: RepositoryIdentity,
        after: RepositoryIdentity,
        started: str,
        *,
        update_mode: str,
    ) -> GraphReceipt:
        graph = Path(index.graph_db).resolve()
        stats = self._graph_stats(graph)
        reasons: list[str] = []
        attempted = max(0, stats.files_attempted)
        files_indexed = max(0, stats.files_parsed)
        coverage = min(1.0, files_indexed / attempted) if attempted else 0.0
        critical_skip_reasons = {"content_read_failed", "metadata_access_failed"}
        critical_skipped = tuple(
            item for item in stats.skipped_paths if item.get("reason") in critical_skip_reasons
        )
        failed_paths = tuple(
            dict.fromkeys(
                (
                    *stats.parse_failure_details,
                    *stats.file_hash_failure_details,
                    *(
                        f"{item.get('path', '')}: {item.get('reason', '')}"
                        for item in critical_skipped
                    ),
                )
            )
        )
        receipt_consistency_errors: list[str] = []
        if attempted + stats.skipped_count != stats.files_discovered:
            receipt_consistency_errors.append("discovery_accounting_mismatch")
        if sum(stats.skipped_reasons.values()) != stats.skipped_count:
            receipt_consistency_errors.append("skip_reason_accounting_mismatch")
        if files_indexed + stats.parse_failures != attempted:
            receipt_consistency_errors.append("parse_accounting_mismatch")
        if stats.file_hashes + stats.file_hash_failures != attempted:
            receipt_consistency_errors.append("file_hash_accounting_mismatch")
        if len(stats.parse_failure_details) != stats.parse_failures:
            receipt_consistency_errors.append("parse_failure_detail_mismatch")
        if len(stats.file_hash_failure_details) != stats.file_hash_failures:
            receipt_consistency_errors.append("file_hash_failure_detail_mismatch")
        if before.source_revision != after.source_revision or before.commit_sha != after.commit_sha:
            status = GraphStatus.STALE
            reasons.append("repository_changed_during_build")
        elif not index.schema_valid:
            status = GraphStatus.FAILED
            reasons.append("graph_schema_invalid")
        elif not stats.receipt_complete:
            status = GraphStatus.FAILED
            reasons.append("graph_discovery_receipt_missing")
        elif receipt_consistency_errors:
            status = GraphStatus.DEGRADED
            reasons.extend(receipt_consistency_errors)
        elif stats.symbols <= 0 or files_indexed <= 0:
            status = GraphStatus.DEGRADED
            reasons.append("suspiciously_empty_graph")
        elif coverage < 0.95:
            status = GraphStatus.DEGRADED
            reasons.append("indexed_file_coverage_below_95_percent")
        elif critical_skipped or stats.file_hash_failures:
            status = GraphStatus.DEGRADED
            if critical_skipped:
                reasons.append(f"source_access_failures:{len(critical_skipped)}")
            if stats.file_hash_failures:
                reasons.append(f"file_hash_failures:{stats.file_hash_failures}")
        elif attempted >= 20 and not stats.edges:
            status = GraphStatus.DEGRADED
            reasons.append("suspicious_graph_has_no_edges")
        elif (
            stats.parse_failures
            or stats.discovery_method != "git_ls_files"
            or any(
                stats.skipped_reasons.get(reason, 0)
                for reason in (
                    "generated",
                    "language_unresolved",
                    "non_regular_file",
                    "too_large",
                )
            )
            or stats.excluded_directories
        ):
            status = GraphStatus.READY_WITH_DECLARED_LIMITATIONS
            if stats.parse_failures:
                reasons.append(f"parser_failures:{stats.parse_failures}")
            if stats.discovery_method != "git_ls_files":
                reasons.append(f"discovery_method:{stats.discovery_method or 'unknown'}")
            for reason in (
                "generated",
                "language_unresolved",
                "non_regular_file",
                "too_large",
            ):
                if count := stats.skipped_reasons.get(reason, 0):
                    reasons.append(f"{reason}:{count}")
            if stats.excluded_directories:
                reasons.append(f"excluded_directory_files:{len(stats.excluded_directories)}")
        else:
            status = GraphStatus.READY
        result = GraphReceipt(
            repository=after.repository,
            commit_sha=after.commit_sha,
            branch=after.branch,
            working_tree_state=after.working_tree_state,
            source_revision=before.source_revision,
            graph_schema_version=stats.schema,
            graph_builder_version=GRAPH_BUILDER_VERSION,
            build_started=started,
            build_completed=self._now(),
            build_status=status,
            files_discovered=max(0, stats.files_discovered),
            files_attempted=attempted,
            files_indexed=files_indexed,
            files_skipped=max(0, stats.skipped_count),
            files_failed=len(failed_paths),
            symbols=stats.symbols,
            nodes_by_type=stats.nodes,
            edges_by_type=stats.edges,
            coverage=coverage,
            build_duration_ms=index.elapsed_ms,
            persistent_graph_path=str(graph),
            graph_checksum_or_identity=index.graph_db_sha256 or self.file_sha256(graph),
            query_ready=status
            in {
                GraphStatus.READY,
                GraphStatus.READY_WITH_DECLARED_LIMITATIONS,
            },
            degraded_reasons=tuple(dict.fromkeys(reason for reason in reasons if reason)),
            repository_files_discovered=after.files_discovered,
            discovery_method=stats.discovery_method,
            skipped_reasons=stats.skipped_reasons,
            skipped_paths=stats.skipped_paths,
            failed_paths=failed_paths,
            excluded_directories=stats.excluded_directories,
            graph_input_hashes=after.graph_input_hashes,
            update_mode=update_mode,
            graph_bytes=graph.stat().st_size,
            source_bytes=after.source_bytes,
        )
        self._write_receipt(result)
        return result

    def build(
        self,
        *,
        force: bool = False,
        timeout: float = 600.0,
        _update_mode: str = "full",
    ) -> GraphReceipt:
        current = self.status()
        if not force and current.query_ready:
            return current
        if not force and current.build_status is GraphStatus.STALE:
            return self.update(timeout=timeout)
        before = compute_repository_identity(self.root)
        started = self._now()
        self._write_receipt(self._empty_receipt(GraphStatus.BUILDING, before, "build_in_progress"))
        index = ensure_index_with_receipt(
            self.root,
            state_dir=self.state_dir,
            source_revision=before.source_revision,
            timeout=timeout,
            exact_state_dir=True,
        )
        after = compute_repository_identity(self.root)
        if not index.graph_db:
            result = replace(
                self._empty_receipt(
                    GraphStatus.FAILED,
                    after,
                    index.status.value,
                    index.error_type or "graph_build_failed",
                    index.error_diagnostic,
                ),
                build_started=started,
                build_completed=self._now(),
                build_duration_ms=index.elapsed_ms,
                files_attempted=index.indexable_files,
                files_failed=index.parser_failures,
                update_mode=_update_mode,
            )
            self._write_receipt(result)
            return result
        return self._finalize_graph_receipt(index, before, after, started, update_mode=_update_mode)

    def update(self, *, timeout: float = 120.0) -> GraphReceipt:
        """Incrementally converge a same-commit stale graph or rebuild safely."""

        observed = self.status()
        if observed.query_ready:
            return observed
        if observed.build_status is not GraphStatus.STALE:
            return self.build(force=True, timeout=timeout, _update_mode="full_fallback")
        current = compute_repository_identity(self.root)
        if (
            observed.commit_sha != current.commit_sha
            or observed.graph_builder_version != GRAPH_BUILDER_VERSION
            or not observed.graph_input_hashes
        ):
            return self.build(force=True, timeout=timeout, _update_mode="full_fallback")

        previous_inputs = observed.graph_input_hashes
        current_inputs = current.graph_input_hashes
        changed = sorted(
            path
            for path in set(previous_inputs) | set(current_inputs)
            if previous_inputs.get(path) != current_inputs.get(path)
        )
        if not changed:
            return self.build(force=True, timeout=timeout, _update_mode="full_fallback")
        if any(path == ".gitmodules" or is_graph_metadata(path) for path in changed):
            return self.build(force=True, timeout=timeout, _update_mode="full_fallback")

        deleted = [path for path in changed if path not in current_inputs]
        added = [path for path in changed if path not in previous_inputs]
        modified = [path for path in changed if path in current_inputs and path in previous_inputs]
        # A delete+add pair may be a rename. Full convergence is currently the
        # only sound way to re-resolve incoming edges across a renamed file.
        if (deleted and added) or len(changed) > max(50, observed.files_attempted // 10):
            return self.build(force=True, timeout=timeout, _update_mode="full_fallback")

        ordered_paths = tuple((*deleted, *added, *modified))
        started = self._now()
        self._write_receipt(
            self._empty_receipt(GraphStatus.BUILDING, current, "incremental_update_in_progress")
        )
        index = refresh_index_files(
            self.root,
            observed.persistent_graph_path,
            ordered_paths,
            timeout=timeout,
            source_revision=current.source_revision,
        )
        after = compute_repository_identity(self.root)
        if not index.graph_db:
            return self.build(force=True, timeout=timeout, _update_mode="full_fallback")
        return self._finalize_graph_receipt(
            index, current, after, started, update_mode="incremental"
        )

    def _ready_graph(self) -> tuple[GraphReceipt, Path]:
        receipt = self.status()
        if not receipt.query_ready:
            reasons = ",".join(receipt.degraded_reasons) or receipt.build_status.value
            raise GraphNotReadyError(f"graph is not query-ready: {reasons}")
        return receipt, Path(receipt.persistent_graph_path)

    def query(
        self,
        mode: str,
        symbol: str,
        *,
        limit: int = 50,
        file_path: str | None = None,
        min_confidence: float = 0.5,
    ) -> dict[str, Any]:
        receipt, graph = self._ready_graph()
        requested = str(mode or "").strip().lower()
        normalized = QUERY_MODE_ALIASES.get(requested, requested)
        if normalized not in CANONICAL_QUERY_MODES:
            choices = ", ".join(CANONICAL_QUERY_MODES)
            raise ValueError(f"unsupported query mode: {mode}; supported modes: {choices}")
        bound = max(1, min(int(limit), 200))
        token = str(symbol or "").strip()
        selected_file = str(file_path or "").strip().replace("\\", "/")
        confidence_floor = max(0.0, min(float(min_confidence), 1.0))
        connection = sqlite3.connect(f"file:{graph.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        resolution_status = "READY"
        resolved_symbol: dict[str, Any] | None = None
        ambiguous_candidates: list[dict[str, Any]] = []
        try:
            node_projection = (
                "n.id,n.label,n.name,n.qualified_name,n.file_path,n.start_line,n.end_line,"
                "n.signature,n.language,n.is_test"
            )
            if normalized == "definition":
                file_clause = "AND n.file_path=?" if selected_file else ""
                parameters: tuple[Any, ...] = (token, token, selected_file, token, bound)
                if not selected_file:
                    parameters = (token, token, token, bound)
                rows = connection.execute(
                    f"SELECT {node_projection} FROM nodes n "
                    f"WHERE (n.name=? OR n.qualified_name=?) {file_clause} "
                    "ORDER BY CASE WHEN n.name=? THEN 0 ELSE 1 END,n.file_path,n.start_line "
                    "LIMIT ?",
                    parameters,
                ).fetchall()
            elif normalized == "search":
                file_clause = "AND n.file_path=?" if selected_file else ""
                parameters = (
                    token,
                    token,
                    f"%{token}%",
                    f"%{token}%",
                    selected_file,
                    token,
                    token,
                    bound,
                )
                if not selected_file:
                    parameters = (
                        token,
                        token,
                        f"%{token}%",
                        f"%{token}%",
                        token,
                        token,
                        bound,
                    )
                rows = connection.execute(
                    f"SELECT {node_projection} FROM nodes n "
                    "WHERE (n.name=? OR n.qualified_name=? OR n.name LIKE ? "
                    f"OR n.qualified_name LIKE ?) {file_clause} "
                    "ORDER BY CASE WHEN n.name=? THEN 0 WHEN n.qualified_name=? THEN 1 ELSE 2 END,"
                    "n.file_path,n.start_line LIMIT ?",
                    parameters,
                ).fetchall()
            else:
                file_clause = "AND n.file_path=?" if selected_file else ""
                anchor_parameters: tuple[Any, ...] = (token, token, selected_file)
                if not selected_file:
                    anchor_parameters = (token, token)
                anchor_rows = connection.execute(
                    f"SELECT {node_projection} FROM nodes n "
                    f"WHERE (n.name=? OR n.qualified_name=?) {file_clause} "
                    "ORDER BY n.file_path,n.start_line",
                    anchor_parameters,
                ).fetchall()
                exact_qualified = [row for row in anchor_rows if row["qualified_name"] == token]
                anchors = exact_qualified if exact_qualified else list(anchor_rows)
                if not anchors:
                    resolution_status = "NOT_FOUND"
                    rows = []
                elif len(anchors) > 1:
                    resolution_status = "AMBIGUOUS"
                    ambiguous_candidates = [dict(row) for row in anchors[:bound]]
                    rows = []
                else:
                    resolved_symbol = dict(anchors[0])
                    anchor_id = int(anchors[0]["id"])
                    reverse = normalized in {
                        "callers",
                        "importers",
                        "implementations",
                        "subclasses",
                        "references",
                        "impact",
                        "tests",
                    }
                    edge_types = {
                        "callers": ("CALLS",),
                        "callees": ("CALLS",),
                        "imports": ("IMPORTS", "IMPORTS_FROM"),
                        "importers": ("IMPORTS", "IMPORTS_FROM"),
                        "implementations": ("IMPLEMENTS",),
                        "subclasses": ("EXTENDS", "INHERITS"),
                        "references": ("REFERENCES", "CALLS", "IMPORTS", "IMPORTS_FROM"),
                        "impact": (
                            "CALLS",
                            "REFERENCES",
                            "IMPORTS",
                            "IMPORTS_FROM",
                            "IMPLEMENTS",
                            "EXTENDS",
                            "INHERITS",
                        ),
                        "tests": ("CALLS", "REFERENCES", "TESTS"),
                    }[normalized]
                    placeholders = ",".join("?" for _ in edge_types)
                    test_clause = "AND n.is_test=1" if normalized == "tests" else ""
                    edge_column = "target_id" if reverse else "source_id"
                    node_column = "source_id" if reverse else "target_id"
                    rows = connection.execute(
                        f"SELECT DISTINCT {node_projection},e.type AS relationship,"
                        "e.source_file,e.source_line,"
                        "e.confidence,e.resolution_method,e.verification_status "
                        f"FROM edges e JOIN nodes n ON n.id=e.{node_column} "
                        f"WHERE e.{edge_column}=? AND e.type IN ({placeholders}) "
                        f"AND e.confidence>=? {test_clause} "
                        "ORDER BY e.confidence DESC,n.file_path,n.start_line LIMIT ?",
                        (anchor_id, *edge_types, confidence_floor, bound),
                    ).fetchall()
        finally:
            connection.close()
        if normalized in {"definition", "search"}:
            resolution_status = "READY" if rows else "NOT_FOUND"
        return {
            "schema": "gt.graph_query.v1",
            "status": resolution_status,
            "mode": normalized,
            "symbol": token,
            "file_path": selected_file,
            "min_confidence": confidence_floor,
            "repository": receipt.repository,
            "commit_sha": receipt.commit_sha,
            "source_revision": receipt.source_revision,
            "graph_identity": receipt.graph_checksum_or_identity,
            "build_status": receipt.build_status.value,
            "evidence": [dict(row) for row in rows],
            "count": len(rows),
            "resolved_symbol": resolved_symbol,
            "ambiguous_candidates": ambiguous_candidates,
            "degraded_reasons": list(receipt.degraded_reasons),
        }


__all__ = [
    "CANONICAL_QUERY_MODES",
    "GraphNotReadyError",
    "GraphReceipt",
    "GraphStatus",
    "RepositoryGraphService",
    "RepositoryIdentity",
    "SUPPORTED_QUERY_MODES",
    "compute_repository_identity",
]
