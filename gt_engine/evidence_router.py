"""Task-role and graph-relevance admission for model-facing GT evidence."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from gt_engine.task_contract import TaskContract

_PATH_RE = re.compile(
    r"(?<![\w.-])(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9_]+"
)
_CALLER_TYPES = frozenset(
    {"caller_contract", "caller_contract_view", "caller_break", "companion_surface"}
)


def _normalized_hash(evidence_type: str, rendered: str) -> str:
    normalized = "\n".join(
        line.strip() for line in (rendered or "").splitlines() if line.strip()
    )
    return hashlib.sha256(
        f"{evidence_type}\0{normalized}".encode("utf-8", "surrogatepass")
    ).hexdigest()


def _paths(text: str) -> set[str]:
    return {p.replace("\\", "/").lower() for p in _PATH_RE.findall(text or "")}


@dataclass
class EvidenceRouter:
    contract: TaskContract
    graph_files: frozenset[str] = frozenset()
    graph_symbols: frozenset[str] = frozenset()
    _delivered: set[str] = field(default_factory=set)

    def admit(
        self,
        evidence_type: str,
        rendered: str,
        *,
        command: str,
        output: str,
        commit: bool = True,
    ) -> tuple[bool, str]:
        fingerprint = _normalized_hash(evidence_type, rendered)
        if fingerprint in self._delivered:
            return False, "semantic_duplicate"

        kind = str(evidence_type or "")
        if self.contract.role == "content_scan" and kind in _CALLER_TYPES:
            return False, "task_role_mismatch"

        rendered_paths = _paths(rendered)
        observed_paths = _paths(f"{command}\n{output}")
        graph_paths = {p.replace("\\", "/").lower() for p in self.graph_files}
        if kind == "localization":
            if self.contract.role == "content_scan" and not (
                rendered_paths & observed_paths
            ):
                return False, "not_grounded_in_content_search"
            if graph_paths and rendered_paths and not (
                rendered_paths & (graph_paths | observed_paths)
            ):
                return False, "graph_unrelated"

        if commit:
            self._delivered.add(fingerprint)
        return True, "admitted"

    def commit(self, evidence_type: str, rendered: str) -> None:
        self._delivered.add(_normalized_hash(evidence_type, rendered))
