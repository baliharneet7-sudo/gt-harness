"""Correct-or-quiet repository evidence for the host-owned central runtime.

The model must not spend its first call rediscovering structure GT can derive
deterministically.  This module turns the existing GroundTruth index and graph
projection into a small source-bound result.  It never invents a caller or a
location when the graph cannot prove one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from gt_engine.graph_context import build_graph_projection
from gt_engine.graph_evidence import build_evidence_need, rank_graph_evidence
from gt_engine.indexer import IndexBuildReceipt, ensure_index_with_receipt
from gt_engine.task_contract import Obligation, TaskContract, extract_task_contract


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

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


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
        self.fresh = False
        self.evidence = RepositoryEvidence(status="not_indexed")
        self.refresh_log: list[dict[str, Any]] = []
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
                if target.is_file() or target.is_symlink():
                    target.unlink()
                continue
            content = after_contents.get(path)
            if not isinstance(content, str):
                self.invalidate(source_revision=source_revision, status="mirror_incomplete")
                return False
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.source_revision = source_revision
        self.fresh = True
        return True

    def refresh(self, *, source_revision: str, limit: int = 8) -> RepositoryEvidence:
        evidence = inspect_repository(
            self.root,
            self.instruction,
            state_dir=self.state_dir,
            limit=limit,
        )
        self.source_revision = source_revision
        self.fresh = evidence.status not in {"mirror_incomplete", "sensor_degraded"}
        self.evidence = evidence
        self.refresh_log.append(
            {
                "source_revision": source_revision,
                "graph_revision": evidence.graph_revision,
                "available": evidence.available,
                "status": evidence.status,
            }
        )
        return evidence

    def summary(self) -> dict[str, Any]:
        return {
            "source_revision": self.source_revision,
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
) -> IndexBuildReceipt:
    """Build the repository graph while retaining its exact availability status."""

    return ensure_index_with_receipt(root, state_dir=state_dir)


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
    connection = sqlite3.connect(
        f"file:{Path(graph_db).resolve().as_posix()}?mode=ro", uri=True
    )
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
                    (item["path"], item["line"], item["symbol"]) == key
                    for item in definitions
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
) -> RepositoryEvidence:
    """Index and rank task-specific source anchors without raising.

    An empty result is deliberate abstention.  Ranked lexical/body facts are
    valid locations.  Callers require an explicit relation surface and caller
    direction; the current graph projection does not expose that direction,
    so this adapter correctly leaves ``callers`` empty for now.
    """
    base = Path(root)
    checks = discover_project_checks(base)
    try:
        index_receipt = inspect_index(
            base, state_dir=state_dir
        )
        graph_db = index_receipt.graph_db
        if not graph_db:
            return RepositoryEvidence(
                project_checks=checks,
                status=index_receipt.status.value,
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
            if not item.file_path:
                continue
            anchor = {
                "path": item.file_path,
                "line": max(0, int(item.line)),
                "symbol": item.symbol,
                "surface": item.surface,
                "confidence": float(item.confidence),
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
                status="no_task_linked_evidence",
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
            status="source_backed",
            index=index_receipt,
        )
    except Exception as exc:
        return RepositoryEvidence(
            project_checks=checks,
            status=f"error:{type(exc).__name__}",
        )
