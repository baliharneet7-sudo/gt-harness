"""Correct-or-quiet repository evidence for the host-owned central runtime.

The model must not spend its first call rediscovering structure GT can derive
deterministically.  This module turns the existing GroundTruth index and graph
projection into a small source-bound result.  It never invents a caller or a
location when the graph cannot prove one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from gt_engine.graph_context import build_graph_projection
from gt_engine.graph_evidence import build_evidence_need, rank_graph_evidence
from gt_engine.indexer import (
    IndexBuildReceipt,
    IndexBuildStatus,
    ensure_index_with_receipt,
    refresh_index_files,
)
from gt_engine.language_registry import is_indexable_source
from gt_engine.task_contract import Obligation, TaskContract, extract_task_contract


class RepositoryIntelligenceStatus(StrEnum):
    HEALTHY_CURRENT = "source_backed"
    NOT_INDEXED = "not_indexed"
    ENVIRONMENT_TRANSFER_UNAVAILABLE = "environment_transfer_unavailable"
    NO_SUPPORTED_SOURCE = "no_supported_source"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    INCOMPLETE_COVERAGE = "incomplete_source_coverage"
    INDEX_UNAVAILABLE = "index_unavailable"
    SCHEMA_INVALID = "schema_invalid"
    STALE = "stale_source_revision"
    EMPTY_RETRIEVAL = "no_task_linked_evidence"
    LOW_PRECISION = "low_precision"
    MIRROR_INCOMPLETE = "mirror_incomplete"
    SENSOR_DEGRADED = "sensor_degraded"


@dataclass(frozen=True, slots=True)
class RepositoryEvidence:
    available: bool = False
    graph_revision: str = ""
    anchors: tuple[dict[str, Any], ...] = ()
    definitions: tuple[dict[str, Any], ...] = ()
    references: tuple[dict[str, Any], ...] = ()
    callers: tuple[dict[str, Any], ...] = ()
    project_checks: tuple[str, ...] = ()
    status: str = "unavailable"
    index: IndexBuildReceipt | None = None
    source_revision: str = ""
    index_current: bool = False
    intelligence_valid: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def graph_gate_failures(evidence: RepositoryEvidence) -> tuple[str, ...]:
    """Return fail-closed reasons for an active task graph gate.

    This is intentionally a substrate gate, not a retrieval-quality oracle.
    A task may still have no task-linked frontier fact, but GT must never enter
    a paid active loop when the graph itself is absent, stale, incomplete, or
    structurally uncertified.
    """

    failures: list[str] = []
    index = evidence.index
    if not evidence.available:
        failures.append(evidence.status or "repository_unavailable")
    if index is None or not index.graph_db:
        failures.append("graph_missing")
    else:
        if not index.schema_valid:
            failures.append("graph_schema_invalid")
        if index.node_count <= 0:
            failures.append("graph_empty")
        if not index.coverage_complete:
            failures.append("graph_source_coverage_incomplete")
        if not index.graph_revision:
            failures.append("graph_revision_missing")
        if not index.source_revision:
            failures.append("graph_source_revision_missing")
        elif evidence.source_revision and index.source_revision != evidence.source_revision:
            failures.append("graph_source_revision_mismatch")
    if not evidence.source_revision:
        failures.append("source_revision_missing")
    if not evidence.index_current:
        failures.append("graph_not_current")
    if not evidence.intelligence_valid:
        failures.append("repository_intelligence_invalid")
    return tuple(dict.fromkeys(failures))


class RepositorySession:
    """Task-scoped host mirror whose graph is bound to a source revision.

    The initial environment transfer is performed by the host agent.  This
    object then applies only source contents captured by the authoritative
    workspace sensor.  Missing content or an unsafe path invalidates the
    mirror; it never serves a stale graph as current evidence.
    """

    def __init__(
        self,
        *,
        root: str | Path,
        state_dir: str | Path,
        instruction: str,
    ) -> None:
        self.root = Path(root).resolve()
        self.state_dir = Path(state_dir).resolve()
        self.instruction = instruction
        self.source_revision = ""
        self.indexed_source_revision = ""
        self.fresh = False
        self.evidence = RepositoryEvidence(status=RepositoryIntelligenceStatus.NOT_INDEXED.value)
        self.refresh_log: list[dict[str, Any]] = []
        self._pending_index_paths: set[str] = set()
        self._requires_full_rebuild = False
        self._owned_directories: tuple[TemporaryDirectory[str], ...] = ()

    @classmethod
    def temporary(cls, *, instruction: str) -> RepositorySession:
        mirror = TemporaryDirectory(prefix="gt-repository-")
        state = TemporaryDirectory(prefix="gt-state-")
        session = cls(root=mirror.name, state_dir=state.name, instruction=instruction)
        session._owned_directories = (mirror, state)
        return session

    def close(self) -> None:
        for directory in reversed(self._owned_directories):
            directory.cleanup()
        self._owned_directories = ()

    def _target(self, relative_path: str) -> Path | None:
        normalized = str(relative_path or "").replace("\\", "/")
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if not normalized or normalized.startswith("/") or ".." in Path(normalized).parts:
            return None
        target = (self.root / normalized).resolve()
        try:
            target.relative_to(self.root)
        except ValueError:
            return None
        return target

    def invalidate(self, *, source_revision: str, status: str) -> None:
        self.source_revision = source_revision
        self.fresh = False
        self.evidence = RepositoryEvidence(
            project_checks=self.evidence.project_checks,
            status=status,
        )

    def apply_transition(
        self,
        transition: Any,
        *,
        source_revision: str,
        changed_paths: tuple[str, ...] | None = None,
    ) -> bool:
        """Advance the mirror only when every changed source has captured text."""
        if not bool(getattr(transition, "sensor_healthy", False)):
            self.invalidate(source_revision=source_revision, status="sensor_degraded")
            return False
        deleted = set(getattr(transition, "deleted", ()) or ())
        after_contents = dict(getattr(transition, "after_contents", {}) or {})
        selected_paths = (
            tuple(changed_paths)
            if changed_paths is not None
            else tuple(getattr(transition, "changed_paths", ()) or ())
        )
        for path in selected_paths:
            target = self._target(str(path))
            if target is None:
                self.invalidate(source_revision=source_revision, status="unsafe_mirror_path")
                return False
            if path in deleted:
                if is_indexable_source(path):
                    self._requires_full_rebuild = True
                if target.is_file() or target.is_symlink():
                    target.unlink()
                continue
            content = after_contents.get(path)
            if not isinstance(content, str):
                self.invalidate(source_revision=source_revision, status="mirror_incomplete")
                return False
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            if is_indexable_source(path):
                self._pending_index_paths.add(str(path).replace("\\", "/"))
        self.source_revision = source_revision
        self.fresh = False
        return True

    def refresh(self, *, source_revision: str, limit: int = 8) -> RepositoryEvidence:
        if source_revision == self.indexed_source_revision and self.evidence.intelligence_valid:
            self.refresh_log.append(
                {
                    "source_revision": source_revision,
                    "graph_revision": self.evidence.graph_revision,
                    "available": self.evidence.available,
                    "status": self.evidence.status,
                    "mode": "revision_cache_hit",
                    "elapsed_ms": 0.0,
                }
            )
            return self.evidence
        prior_index = self.evidence.index
        mode = "full"
        if prior_index is not None and prior_index.graph_db and not self._requires_full_rebuild:
            if self._pending_index_paths:
                mode = "incremental"
                index_receipt = refresh_index_files(
                    self.root,
                    prior_index.graph_db,
                    tuple(sorted(self._pending_index_paths)),
                    source_revision=source_revision,
                )
                evidence = inspect_repository(
                    self.root,
                    self.instruction,
                    state_dir=self.state_dir,
                    limit=limit,
                    index_receipt=index_receipt,
                    source_revision=source_revision,
                )
            else:
                mode = "source_revision_only"
                evidence = self.evidence
        else:
            evidence = inspect_repository(
                self.root,
                self.instruction,
                state_dir=self.state_dir,
                limit=limit,
                source_revision=source_revision,
            )
        evidence = replace(
            evidence,
            source_revision=source_revision,
            index_current=bool(evidence.available and source_revision),
            intelligence_valid=bool(
                evidence.available
                and evidence.status == RepositoryIntelligenceStatus.HEALTHY_CURRENT.value
                and source_revision
            ),
        )
        self.source_revision = source_revision
        self.indexed_source_revision = source_revision
        self.fresh = evidence.intelligence_valid
        self.evidence = evidence
        self._pending_index_paths.clear()
        self._requires_full_rebuild = False
        self.refresh_log.append(
            {
                "source_revision": source_revision,
                "graph_revision": evidence.graph_revision,
                "available": evidence.available,
                "status": evidence.status,
                "mode": mode,
                "elapsed_ms": (
                    float(evidence.index.elapsed_ms) if evidence.index is not None else 0.0
                ),
            }
        )
        return evidence

    def summary(self) -> dict[str, Any]:
        return {
            "source_revision": self.source_revision,
            "indexed_source_revision": self.indexed_source_revision,
            "fresh": self.fresh,
            "evidence": self.evidence.as_dict(),
            "refresh_log": list(self.refresh_log),
        }


def discover_project_checks(root: str | Path) -> tuple[str, ...]:
    """Return only conventional, repository-backed verification commands."""
    base = Path(root)
    checks: list[str] = []
    if (base / "pyproject.toml").is_file() or (base / "pytest.ini").is_file():
        checks.append("pytest -q")
    if (base / "package.json").is_file():
        checks.append("npm test")
    if (base / "Cargo.toml").is_file():
        checks.append("cargo test")
    if (base / "go.mod").is_file():
        checks.append("go test ./...")
    if (base / "Makefile").is_file() or (base / "makefile").is_file():
        checks.append("make test")
    return tuple(dict.fromkeys(checks))


def inspect_index(
    root: str | Path,
    *,
    state_dir: str | Path | None = None,
    source_revision: str = "",
) -> IndexBuildReceipt:
    """Build the repository graph while retaining its exact availability status."""

    return ensure_index_with_receipt(
        root, state_dir=state_dir, source_revision=source_revision
    )


def _graph_structural_roles(
    graph_db: str,
    anchors: tuple[dict[str, Any], ...],
    *,
    limit: int,
) -> tuple[
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
]:
    """Resolve definitions, call references, and direct callers from graph identity."""

    definitions: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    callers: list[dict[str, Any]] = []
    target_ids: list[int] = []
    connection = sqlite3.connect(f"file:{Path(graph_db).resolve().as_posix()}?mode=ro", uri=True)
    try:
        for anchor in anchors:
            path = str(anchor.get("path") or "")
            symbol = str(anchor.get("symbol") or "")
            line = int(anchor.get("line") or 0)
            if not path:
                continue
            rows = connection.execute(
                "SELECT id,label,name,COALESCE(qualified_name,''),file_path,"
                "COALESCE(start_line,0),COALESCE(signature,''),language "
                "FROM nodes WHERE file_path=? AND "
                "((?<>'' AND name=?) OR (? > 0 AND start_line=?)) "
                "ORDER BY CASE WHEN name=? THEN 0 ELSE 1 END,start_line,id LIMIT 4",
                (path, symbol, symbol, line, line, symbol),
            ).fetchall()
            for row in rows:
                node_id = int(row[0])
                definition = {
                    "path": str(row[4]),
                    "line": int(row[5]),
                    "symbol": str(row[2]),
                    "qualified_symbol": str(row[3]),
                    "kind": str(row[1]),
                    "signature": str(row[6]),
                    "language": str(row[7]),
                    "semantics": "graph_definition",
                }
                key = (definition["path"], definition["line"], definition["symbol"])
                if not any(
                    (item["path"], item["line"], item["symbol"]) == key for item in definitions
                ):
                    definitions.append(definition)
                    target_ids.append(node_id)
                if len(definitions) >= limit:
                    break
            if len(definitions) >= limit:
                break
        for target_id in dict.fromkeys(target_ids):
            rows = connection.execute(
                "SELECT src.name,src.file_path,COALESCE(e.source_line,src.start_line,0),"
                "tgt.name,tgt.file_path,COALESCE(e.resolution_method,''),"
                "COALESCE(e.confidence,0),COALESCE(e.trust_tier,''),"
                "COALESCE(e.candidate_count,0),COALESCE(e.evidence_type,'') "
                "FROM edges e JOIN nodes src ON src.id=e.source_id "
                "JOIN nodes tgt ON tgt.id=e.target_id "
                "WHERE e.type='CALLS' AND e.target_id=? "
                "AND COALESCE(e.confidence,0)>=0.95 "
                "AND COALESCE(e.trust_tier,'')='CERTIFIED' "
                "AND COALESCE(e.candidate_count,0)=1 "
                "ORDER BY src.file_path,e.source_line,src.name LIMIT ?",
                (target_id, limit),
            ).fetchall()
            for row in rows:
                reference = {
                    "path": str(row[1]),
                    "line": int(row[2]),
                    "symbol": str(row[3]),
                    "semantics": "graph_call_reference",
                }
                caller = {
                    "caller": str(row[0]),
                    "caller_path": str(row[1]),
                    "caller_line": int(row[2]),
                    "target": str(row[3]),
                    "target_path": str(row[4]),
                    "resolution_method": str(row[5]),
                    "confidence": float(row[6]),
                    "trust_tier": str(row[7]),
                    "candidate_count": int(row[8]),
                    "evidence_type": str(row[9]),
                    "semantics": "graph_recorded",
                }
                if reference not in references:
                    references.append(reference)
                if caller not in callers:
                    callers.append(caller)
                if len(callers) >= limit:
                    break
            if len(callers) >= limit:
                break
    finally:
        connection.close()
    return tuple(definitions), tuple(references), tuple(callers)


def inspect_repository(
    root: str | Path,
    instruction: str,
    *,
    state_dir: str | Path | None = None,
    limit: int = 8,
    index_receipt: IndexBuildReceipt | None = None,
    source_revision: str = "",
) -> RepositoryEvidence:
    """Index and rank task-specific source anchors without raising.

    An empty result is deliberate abstention. Ranked lexical/body facts become
    anchors only with a concrete symbol, positive line, and high retrieval
    confidence. Callers require a certified directed CALLS edge; ambiguous or
    heuristic relations remain absent.
    """
    base = Path(root)
    checks = discover_project_checks(base)
    try:
        index_receipt = index_receipt or inspect_index(
            base, state_dir=state_dir, source_revision=source_revision
        )
        graph_db = index_receipt.graph_db
        if not graph_db:
            status = {
                IndexBuildStatus.NO_SUPPORTED_SOURCE: (
                    RepositoryIntelligenceStatus.NO_SUPPORTED_SOURCE.value
                ),
                IndexBuildStatus.UNSUPPORTED_LANGUAGE: (
                    RepositoryIntelligenceStatus.UNSUPPORTED_LANGUAGE.value
                ),
                IndexBuildStatus.INCOMPLETE_COVERAGE: (
                    RepositoryIntelligenceStatus.INCOMPLETE_COVERAGE.value
                ),
                IndexBuildStatus.INVALID_DATABASE: (
                    RepositoryIntelligenceStatus.SCHEMA_INVALID.value
                ),
            }.get(index_receipt.status, RepositoryIntelligenceStatus.INDEX_UNAVAILABLE.value)
            return RepositoryEvidence(
                project_checks=checks,
                status=status,
                index=index_receipt,
            )
        if not index_receipt.schema_valid:
            return RepositoryEvidence(
                graph_revision=index_receipt.graph_revision,
                project_checks=checks,
                status=RepositoryIntelligenceStatus.SCHEMA_INVALID.value,
                index=index_receipt,
            )
        if index_receipt.status is IndexBuildStatus.INCOMPLETE_COVERAGE:
            return RepositoryEvidence(
                graph_revision=index_receipt.graph_revision,
                project_checks=checks,
                status=RepositoryIntelligenceStatus.INCOMPLETE_COVERAGE.value,
                index=index_receipt,
            )
        contract = extract_task_contract(instruction)
        if not contract.obligations and instruction.strip():
            # The strict contract extractor intentionally ignores prose that
            # contains no explicit modal requirement.  Localization still
            # needs lexical task anchors, so retain that prose as one bounded
            # search obligation without pretending it is a verifier oracle.
            contract = TaskContract(
                role=contract.role,
                task_mode=contract.task_mode,
                predicates=contract.predicates,
                obligations=(
                    Obligation(
                        obligation_id="task:instruction",
                        text=" ".join(instruction.split())[:2000],
                        source="instruction",
                    ),
                ),
            )
        projection = build_graph_projection(graph_db, contract, limit=max(8, limit * 2))
        need = build_evidence_need(contract, projection, boundary="task_start")
        ranked = rank_graph_evidence(contract, projection, need, limit=limit)
        anchors: list[dict[str, Any]] = []
        for item in ranked:
            if (
                not item.file_path
                or not item.symbol
                or int(item.line) <= 0
                or float(item.confidence) < 0.95
            ):
                continue
            anchor = {
                "path": item.file_path,
                "line": int(item.line),
                "symbol": item.symbol,
                "surface": item.surface,
                "confidence": float(item.confidence),
                "retrieval_relevance": float(item.confidence),
                "semantic_certainty": 1.0,
            }
            key = (anchor["path"], anchor["line"], anchor["symbol"])
            if any((row["path"], row["line"], row["symbol"]) == key for row in anchors):
                continue
            anchors.append(anchor)
            if len(anchors) >= 4:
                break
        if not anchors:
            return RepositoryEvidence(
                graph_revision=projection.revision,
                project_checks=checks,
                status=RepositoryIntelligenceStatus.EMPTY_RETRIEVAL.value,
                index=index_receipt,
            )
        definitions, references, callers = _graph_structural_roles(
            graph_db,
            tuple(anchors),
            limit=max(1, limit),
        )
        return RepositoryEvidence(
            available=True,
            graph_revision=projection.revision,
            anchors=tuple(anchors),
            definitions=definitions,
            references=references,
            callers=callers,
            project_checks=checks,
            status=RepositoryIntelligenceStatus.HEALTHY_CURRENT.value,
            index=index_receipt,
            intelligence_valid=True,
        )
    except Exception as exc:
        return RepositoryEvidence(
            project_checks=checks,
            status=RepositoryIntelligenceStatus.INDEX_UNAVAILABLE.value,
            index=IndexBuildReceipt(
                IndexBuildStatus.BUILD_FAILED,
                error_type=type(exc).__name__,
            ),
        )
