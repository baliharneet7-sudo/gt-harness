"""Correct-or-quiet repository evidence for the host-owned central runtime.

The model must not spend its first call rediscovering structure GT can derive
deterministically.  This module turns the existing GroundTruth index and graph
projection into a small source-bound result.  It never invents a caller or a
location when the graph cannot prove one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from gt_engine.graph_context import build_graph_projection
from gt_engine.graph_evidence import build_evidence_need, rank_graph_evidence
from gt_engine.indexer import ensure_index
from gt_engine.task_contract import Obligation, TaskContract, extract_task_contract


@dataclass(frozen=True, slots=True)
class RepositoryEvidence:
    available: bool = False
    graph_revision: str = ""
    anchors: tuple[dict[str, Any], ...] = ()
    callers: tuple[dict[str, Any], ...] = ()
    project_checks: tuple[str, ...] = ()
    status: str = "unavailable"

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
        graph_db = ensure_index(
            str(base), state_dir=str(state_dir) if state_dir is not None else None
        )
        if not graph_db:
            return RepositoryEvidence(project_checks=checks, status="index_unavailable")
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
            )
        return RepositoryEvidence(
            available=True,
            graph_revision=projection.revision,
            anchors=tuple(anchors),
            callers=(),
            project_checks=checks,
            status="source_backed",
        )
    except Exception as exc:
        return RepositoryEvidence(
            project_checks=checks,
            status=f"error:{type(exc).__name__}",
        )
