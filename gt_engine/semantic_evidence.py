"""Compose bounded semantic evidence from GT's existing repository substrate.

This is an adapter, not a second indexer.  It turns the source-backed
``RepositoryEvidence`` rows already produced by GT into one compact,
revision-bound semantic view.  Weak, ambiguous, or incomplete rows are
discarded; they never become corrective advice.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from gt_engine.repository_intelligence import RepositoryEvidence


class SemanticEvidenceStatus(StrEnum):
    DELIVER = "deliver"
    ABSTAIN = "abstain"


class SemanticAuthority(StrEnum):
    """Producer authority for a semantic item, independent of relevance."""

    COMPILER = "COMPILER"
    LSP = "LSP"
    PARSER_STRUCTURAL = "PARSER_STRUCTURAL"
    HEURISTIC = "HEURISTIC"
    TEXTUAL = "TEXTUAL"


_HEALTHY_STATUS = "source_backed"
_MIN_CERTAINTY = 0.95
_MIN_RELEVANCE = 0.95
_CERTIFIED_TRUST = "CERTIFIED"


@dataclass(frozen=True, slots=True)
class SemanticEvidenceProfile:
    """Receipt-visible bounds for the semantic evidence bridge."""

    profile_id: str = "semantic-evidence-v1"
    max_items: int = 6
    max_tokens: int = 192
    certainty_threshold: float = _MIN_CERTAINTY
    relevance_threshold: float = _MIN_RELEVANCE


FINAL_SEMANTIC_EVIDENCE_PROFILE = SemanticEvidenceProfile()


def _tokens(value: str) -> int:
    return len(re.findall(r"\w+|[^\w\s]", str(value or ""), re.UNICODE))


def _path(value: object) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _line(value: object) -> int:
    """Return a safe positive integer, or zero for malformed input."""
    try:
        parsed = int(str(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0
    return parsed if parsed > 0 else 0


def _claim_id(
    *,
    kind: str,
    path: str,
    line: int,
    symbol: str,
    relation: str,
    value: str,
    signature: str,
) -> str:
    material = "\0".join(
        (
            kind,
            path,
            str(line),
            symbol,
            relation,
            value,
            signature,
        )
    )
    return "gt-semantic-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _semantic_authority(*values: object) -> SemanticAuthority:
    material = " ".join(
        str(value or "").lower()
        for value in values
        if value is not None
    )
    if "scip" in material or "compiler" in material:
        return SemanticAuthority.COMPILER
    if "lsp" in material:
        return SemanticAuthority.LSP
    if any(token in material for token in ("tree_sitter", "treesitter", "ast", "graph_node")):
        return SemanticAuthority.PARSER_STRUCTURAL
    if material.strip():
        return SemanticAuthority.HEURISTIC
    return SemanticAuthority.TEXTUAL


@dataclass(frozen=True, slots=True)
class SemanticEvidenceItem:
    kind: str
    path: str
    line: int
    symbol: str
    relation: str
    value: str
    signature: str
    return_type: str
    origin: str
    resolution_outcome: str
    provenance: tuple[str, ...]
    source_revision: str
    graph_revision: str
    semantic_certainty: float
    retrieval_relevance: float
    claim_id: str
    semantic_authority: SemanticAuthority = SemanticAuthority.PARSER_STRUCTURAL

    @property
    def rendered(self) -> str:
        location = f"{self.path}:{self.line}"
        if self.kind == "definition":
            detail = self.signature or self.symbol
            if self.return_type and self.return_type not in detail:
                detail += f" -> {self.return_type}"
            return f"- Definition {location} {self.symbol}: {detail}"
        if self.kind == "caller":
            return f"- Caller {location} {self.symbol} calls {self.value}"
        if self.kind == "test":
            return f"- Test {location} {self.symbol}"
        if self.kind == "property":
            return f"- {self.relation} {location} {self.symbol}: {self.value}"
        return f"- Reference {location} {self.symbol}"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SemanticEvidenceResult:
    status: SemanticEvidenceStatus
    items: tuple[SemanticEvidenceItem, ...]
    rendered_text: str
    claim_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    source_revision: str
    graph_revision: str
    token_count: int
    truncated_count: int = 0

    @property
    def item_count(self) -> int:
        return len(self.items)

    def as_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["status"] = self.status.value
        row["items"] = [item.as_dict() for item in self.items]
        row["claim_ids"] = list(self.claim_ids)
        row["reason_codes"] = list(self.reason_codes)
        return row


class SemanticEvidenceBridge:
    """Convert certified repository rows into one bounded semantic answer."""

    def __init__(
        self,
        *,
        max_items: int = FINAL_SEMANTIC_EVIDENCE_PROFILE.max_items,
        max_tokens: int = FINAL_SEMANTIC_EVIDENCE_PROFILE.max_tokens,
        certainty_threshold: float = FINAL_SEMANTIC_EVIDENCE_PROFILE.certainty_threshold,
        relevance_threshold: float = FINAL_SEMANTIC_EVIDENCE_PROFILE.relevance_threshold,
    ) -> None:
        self.max_items = max(1, int(max_items))
        self.max_tokens = max(1, int(max_tokens))
        self.certainty_threshold = float(certainty_threshold)
        self.relevance_threshold = float(relevance_threshold)

    @staticmethod
    def _row(evidence: RepositoryEvidence | Mapping[str, Any]) -> Mapping[str, Any]:
        return evidence.as_dict() if isinstance(evidence, RepositoryEvidence) else evidence

    @staticmethod
    def _score(
        row: Mapping[str, Any], *, default_certainty: float = 0.0
    ) -> tuple[float, float]:
        try:
            certainty = float(
                row.get("semantic_certainty")
                or row.get("confidence")
                or default_certainty
            )
        except (TypeError, ValueError, OverflowError):
            certainty = -1.0
        try:
            relevance = float(row.get("retrieval_relevance") or 0.0)
        except (TypeError, ValueError, OverflowError):
            relevance = -1.0
        return certainty, relevance

    def _valid_score(self, certainty: float, relevance: float) -> bool:
        return (
            0.0 <= certainty <= 1.0
            and 0.0 <= relevance <= 1.0
            and certainty >= self.certainty_threshold
            and relevance >= self.relevance_threshold
        )

    def _definition_items(
        self, row: Mapping[str, Any], source_revision: str, graph_revision: str, reasons: list[str]
    ) -> list[SemanticEvidenceItem]:
        items: list[SemanticEvidenceItem] = []
        for item in row.get("definitions") or ():
            if not isinstance(item, Mapping):
                reasons.append("invalid_definition_rejected")
                continue
            path = _path(item.get("path"))
            symbol = str(item.get("symbol") or "").strip()
            line = _line(item.get("line"))
            certainty, relevance = self._score(item, default_certainty=1.0 if line > 0 else 0.0)
            if not path or not symbol or line < 1:
                reasons.append("incomplete_definition_rejected")
                continue
            origin = str(item.get("origin") or "unknown")
            resolution_outcome = str(item.get("resolution_outcome") or "unknown")
            provenance = tuple(str(value) for value in item.get("provenance") or ())
            if origin != "program" or resolution_outcome != "exact" or not provenance:
                reasons.append("ambiguous_definition_rejected")
                continue
            if not self._valid_score(certainty, relevance):
                reasons.append("weak_definition_rejected")
                continue
            signature = " ".join(str(item.get("signature") or "").split())
            return_type = " ".join(str(item.get("return_type") or "").split())
            items.append(
                SemanticEvidenceItem(
                    kind="definition",
                    path=path,
                    line=line,
                    symbol=symbol,
                    relation="defines",
                    value=symbol,
                    signature=signature,
                    return_type=return_type,
                    origin=origin,
                    resolution_outcome=resolution_outcome,
                    provenance=provenance,
                    source_revision=source_revision,
                    graph_revision=graph_revision,
                    semantic_certainty=certainty,
                    retrieval_relevance=relevance,
                    claim_id=_claim_id(
                        kind="definition",
                        path=path,
                        line=line,
                        symbol=symbol,
                        relation="defines",
                        value=symbol,
                        signature=signature,
                    ),
                    semantic_authority=_semantic_authority(*provenance),
                )
            )
        return items

    def _caller_items(
        self, row: Mapping[str, Any], source_revision: str, graph_revision: str, reasons: list[str]
    ) -> list[SemanticEvidenceItem]:
        items: list[SemanticEvidenceItem] = []
        for item in row.get("callers") or ():
            if not isinstance(item, Mapping):
                reasons.append("invalid_caller_rejected")
                continue
            path = _path(item.get("caller_path"))
            symbol = str(item.get("caller") or item.get("caller_symbol") or "").strip()
            target = str(item.get("target") or item.get("target_symbol") or "").strip()
            line = _line(item.get("caller_line"))
            certainty, relevance = self._score(item)
            certified = (
                str(item.get("trust_tier") or "").upper() == _CERTIFIED_TRUST
                and _line(item.get("candidate_count")) == 1
                and str(item.get("semantics") or "") == "graph_recorded"
                and str(item.get("origin") or "unknown") == "program"
                and str(item.get("resolution_outcome") or "unknown") == "exact"
            )
            if not path or not symbol or not target or line < 1:
                reasons.append("incomplete_caller_rejected")
                continue
            if not certified or not self._valid_score(certainty, relevance):
                reasons.append(
                    "ambiguous_caller_rejected"
                    if not certified
                    else "weak_caller_rejected"
                )
                continue
            items.append(
                SemanticEvidenceItem(
                    kind="caller",
                    path=path,
                    line=line,
                    symbol=symbol,
                    relation="calls",
                    value=target,
                    signature="",
                    return_type="",
                    origin=str(item.get("origin") or "unknown"),
                    resolution_outcome=str(
                        item.get("resolution_outcome") or "unknown"
                    ),
                    provenance=(
                        f"resolution_method:{item.get('resolution_method') or 'unknown'}",
                        f"evidence_type:{item.get('evidence_type') or 'unknown'}",
                    ),
                    source_revision=source_revision,
                    graph_revision=graph_revision,
                    semantic_certainty=certainty,
                    retrieval_relevance=relevance,
                    claim_id=_claim_id(
                        kind="caller",
                        path=path,
                        line=line,
                        symbol=symbol,
                        relation="calls",
                        value=target,
                        signature="",
                    ),
                    semantic_authority=_semantic_authority(
                        item.get("resolution_method"),
                        item.get("evidence_type"),
                    ),
                )
            )
        return items

    def _reference_items(
        self, row: Mapping[str, Any], source_revision: str, graph_revision: str, reasons: list[str]
    ) -> list[SemanticEvidenceItem]:
        items: list[SemanticEvidenceItem] = []
        for item in row.get("references") or ():
            if not isinstance(item, Mapping):
                reasons.append("invalid_reference_rejected")
                continue
            path = _path(item.get("path"))
            symbol = str(item.get("symbol") or "").strip()
            line = _line(item.get("line"))
            certainty, relevance = self._score(item, default_certainty=1.0 if line > 0 else 0.0)
            if not path or not symbol or line < 1:
                reasons.append("incomplete_reference_rejected")
                continue
            origin = str(item.get("origin") or "unknown")
            resolution_outcome = str(item.get("resolution_outcome") or "unknown")
            provenance = tuple(str(value) for value in item.get("provenance") or ())
            if origin != "program" or resolution_outcome != "exact" or not provenance:
                reasons.append("ambiguous_reference_rejected")
                continue
            if not self._valid_score(certainty, relevance):
                reasons.append("weak_reference_rejected")
                continue
            is_test = bool(item.get("is_test"))
            kind = "test" if is_test else "reference"
            items.append(
                SemanticEvidenceItem(
                    kind=kind,
                    path=path,
                    line=line,
                    symbol=symbol,
                    relation="references",
                    value=str(item.get("target") or symbol),
                    signature="",
                    return_type="",
                    origin=origin,
                    resolution_outcome=resolution_outcome,
                    provenance=provenance,
                    source_revision=source_revision,
                    graph_revision=graph_revision,
                    semantic_certainty=certainty,
                    retrieval_relevance=relevance,
                    claim_id=_claim_id(
                        kind=kind,
                        path=path,
                        line=line,
                        symbol=symbol,
                        relation="references",
                        value=str(item.get("target") or symbol),
                        signature="",
                    ),
                    semantic_authority=_semantic_authority(*provenance),
                )
            )
        return items

    def _property_items(
        self, row: Mapping[str, Any], source_revision: str, graph_revision: str, reasons: list[str]
    ) -> list[SemanticEvidenceItem]:
        items: list[SemanticEvidenceItem] = []
        allowed_kinds = {
            "param",
            "return_shape",
            "class_field",
            "visibility",
            "class_decorator",
        }
        for item in row.get("semantic_properties") or ():
            if not isinstance(item, Mapping):
                reasons.append("invalid_semantic_property_rejected")
                continue
            path = _path(item.get("path"))
            symbol = str(item.get("symbol") or "").strip()
            line = _line(item.get("line"))
            kind = str(item.get("kind") or "").strip()
            value = " ".join(str(item.get("value") or "").split())
            certainty, relevance = self._score(item)
            certified = (
                str(item.get("trust_tier") or "").upper() == _CERTIFIED_TRUST
                and str(item.get("origin") or "") == "program"
                and str(item.get("resolution_outcome") or "") == "exact"
                and bool(str(item.get("evidence_method") or "").strip())
                and str(item.get("verification_status") or "").lower() == "verified"
            )
            if kind not in allowed_kinds:
                continue
            if not path or not symbol or not value or line < 1:
                reasons.append("incomplete_semantic_property_rejected")
                continue
            if not certified or not self._valid_score(certainty, relevance):
                reasons.append(
                    "unverified_semantic_property_rejected"
                    if (
                        str(item.get("trust_tier") or "").upper() == _CERTIFIED_TRUST
                        and str(item.get("origin") or "") == "program"
                        and str(item.get("resolution_outcome") or "") == "exact"
                        and str(item.get("verification_status") or "").lower()
                        != "verified"
                    )
                    else "weak_semantic_property_rejected"
                )
                continue
            items.append(
                SemanticEvidenceItem(
                    kind="property",
                    path=path,
                    line=line,
                    symbol=symbol,
                    relation=kind.replace("_", " ").title(),
                    value=value,
                    signature="",
                    return_type="",
                    origin="program",
                    resolution_outcome="exact",
                    provenance=(
                        f"property_id:{item.get('property_id') or 'unknown'}",
                        f"evidence_method:{item.get('evidence_method')}",
                        f"verification_status:{item.get('verification_status') or 'unknown'}",
                    ),
                    source_revision=source_revision,
                    graph_revision=graph_revision,
                    semantic_certainty=certainty,
                    retrieval_relevance=relevance,
                    claim_id=_claim_id(
                        kind="property",
                        path=path,
                        line=line,
                        symbol=symbol,
                        relation=kind,
                        value=value,
                        signature="",
                    ),
                    semantic_authority=_semantic_authority(
                        item.get("evidence_method"),
                        item.get("extractor"),
                    ),
                )
            )
        return items

    def _abstain(
        self,
        source_revision: str,
        graph_revision: str,
        reasons: list[str],
    ) -> SemanticEvidenceResult:
        return SemanticEvidenceResult(
            status=SemanticEvidenceStatus.ABSTAIN,
            items=(),
            rendered_text="",
            claim_ids=(),
            reason_codes=tuple(dict.fromkeys(reasons)),
            source_revision=source_revision,
            graph_revision=graph_revision,
            token_count=0,
        )

    def compose(
        self,
        evidence: RepositoryEvidence | Mapping[str, Any],
        *,
        source_revision: str,
        graph_revision: str,
        delivered_claim_ids: frozenset[str] = frozenset(),
    ) -> SemanticEvidenceResult:
        row = self._row(evidence)
        reasons: list[str] = []
        evidence_source = str(row.get("source_revision") or "")
        evidence_graph = str(row.get("graph_revision") or "")
        if evidence_source != source_revision:
            reasons.append("source_revision_mismatch")
        if evidence_graph != graph_revision:
            reasons.append("graph_revision_mismatch")
        if str(row.get("status") or "") != _HEALTHY_STATUS:
            reasons.append("repository_evidence_unavailable")
        if not bool(row.get("substrate_ready")):
            reasons.append("repository_substrate_unavailable")
        if not bool(row.get("index_current")):
            reasons.append("repository_index_not_current")
        if not bool(row.get("intelligence_valid")):
            reasons.append("repository_intelligence_not_valid")
        if reasons:
            return self._abstain(source_revision, graph_revision, reasons)

        items = [
            *self._definition_items(row, source_revision, graph_revision, reasons),
            *self._caller_items(row, source_revision, graph_revision, reasons),
            *self._reference_items(row, source_revision, graph_revision, reasons),
            *self._property_items(row, source_revision, graph_revision, reasons),
        ]
        unique: dict[str, SemanticEvidenceItem] = {item.claim_id: item for item in items}
        if delivered_claim_ids:
            unique = {
                claim_id: item
                for claim_id, item in unique.items()
                if claim_id not in delivered_claim_ids
            }
            if not unique and items:
                reasons.append("semantic_evidence_already_delivered")
        ordered = sorted(
            unique.values(),
            key=lambda item: (
                {"definition": 0, "property": 1, "caller": 2, "test": 3, "reference": 4}.get(
                    item.kind, 99
                ),
                item.path.lower(),
                item.line,
                item.symbol,
                item.claim_id,
            ),
        )
        selected: list[SemanticEvidenceItem] = []
        used_tokens = 0
        truncated = 0
        for item in ordered:
            if (
                len(selected) >= self.max_items
                or used_tokens + _tokens(item.rendered) > self.max_tokens
            ):
                truncated += 1
                continue
            selected.append(item)
            used_tokens += _tokens(item.rendered)
        if not selected:
            reasons.append("no_certified_semantic_evidence")
            return self._abstain(source_revision, graph_revision, reasons)

        heading = "Certified semantic context (source-backed; omitted facts may exist):"
        rendered = "\n".join((heading, *(item.rendered for item in selected)))
        return SemanticEvidenceResult(
            status=SemanticEvidenceStatus.DELIVER,
            items=tuple(selected),
            rendered_text=rendered,
            claim_ids=tuple(item.claim_id for item in selected),
            reason_codes=tuple(dict.fromkeys(reasons)),
            source_revision=source_revision,
            graph_revision=graph_revision,
            token_count=_tokens(rendered),
            truncated_count=truncated,
        )


__all__ = [
    "SemanticAuthority",
    "FINAL_SEMANTIC_EVIDENCE_PROFILE",
    "SemanticEvidenceBridge",
    "SemanticEvidenceItem",
    "SemanticEvidenceProfile",
    "SemanticEvidenceResult",
    "SemanticEvidenceStatus",
]
