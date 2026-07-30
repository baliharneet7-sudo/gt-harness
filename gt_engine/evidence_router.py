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
_COMPLETE_SCOPE_RE = re.compile(
    r"(?i)\b(?:all|any|entire|whole|throughout|across)\b.{0,48}"
    r"\b(?:repository|repo|files?|information|values?|keys?|secrets?)\b"
    r"|\b(?:not present|none remain|remove all|find and remove all)\b"
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


def _requires_complete_scope(contract: TaskContract) -> bool:
    return any(
        _COMPLETE_SCOPE_RE.search(str(item.text or ""))
        for item in contract.obligations
    )


@dataclass
class EvidenceRouter:
    contract: TaskContract
    graph_files: frozenset[str] = frozenset()
    graph_symbols: frozenset[str] = frozenset()
    graph_revision: str = ""
    _delivered: set[str] = field(default_factory=set)
    _scope_challenge_candidates: set[str] = field(default_factory=set)
    _scope_challenge_delivered: bool = False

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
                graph_grounded = bool(rendered_paths & graph_paths)
                if (
                    graph_grounded
                    and _requires_complete_scope(self.contract)
                    and not self._scope_challenge_delivered
                ):
                    # A narrowed search is an observation, not the boundary of
                    # repository truth.  One graph-grounded candidate may
                    # challenge incomplete scope; the normal dose arbiter still
                    # decides whether it ships.
                    self._scope_challenge_candidates.add(fingerprint)
                    if commit:
                        self._scope_challenge_delivered = True
                    reason = "graph_scope_challenge"
                elif self._scope_challenge_delivered and graph_grounded:
                    return False, "scope_challenge_already_delivered"
                else:
                    return False, "not_grounded_in_content_search"
            else:
                reason = "admitted"
            if graph_paths and rendered_paths and not (
                rendered_paths & (graph_paths | observed_paths)
            ):
                return False, "graph_unrelated"
        else:
            reason = "admitted"

        if commit:
            self._delivered.add(fingerprint)
        return True, reason

    def commit(self, evidence_type: str, rendered: str) -> None:
        fingerprint = _normalized_hash(evidence_type, rendered)
        self._delivered.add(fingerprint)
        if fingerprint in self._scope_challenge_candidates:
            self._scope_challenge_delivered = True

    def carry_delivery_state_from(self, prior: EvidenceRouter | None) -> None:
        """Preserve semantic deduplication across a graph-context refresh."""
        if prior is not None:
            self._delivered.update(prior._delivered)
            self._scope_challenge_delivered = prior._scope_challenge_delivered
