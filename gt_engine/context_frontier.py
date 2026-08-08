"""Bounded deterministic repository context that advances beyond Mini-SWE history."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from gt_engine.repository_intelligence import (
    RepositoryEvidence,
    RepositoryIntelligenceStatus,
)


class ContextFrontierKind(StrEnum):
    FILE = "file"
    SYMBOL = "symbol"
    DEFINITION = "definition"
    SIGNATURE = "signature"
    CALLER = "caller"
    REFERENCE = "reference"
    TEST = "test"
    COUPLED_FILE = "coupled_file"
    PRECEDENT = "precedent"
    VALIDATION = "validation"


class FrontierDisposition(StrEnum):
    SELECTED_FRONTIER = "selected_frontier"
    REPRESENTED_MESSAGE = "represented_message"
    SUBSTRATE_FAILURE = "substrate_failure"
    STALE_SOURCE_REVISION = "stale_source_revision"
    LOW_PRECISION = "low_precision"
    FRONTIER_BUDGET = "frontier_budget"
    NO_FRONTIER = "no_frontier"


@dataclass(frozen=True, slots=True)
class ContextFrontierFact:
    fact_id: str
    kind: ContextFrontierKind
    path: str
    line: int = 0
    symbol: str = ""
    value: str = ""
    relation: str = ""
    source_revision: str = ""
    graph_revision: str = ""
    semantic_certainty: float = 0.0
    retrieval_relevance: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["kind"] = self.kind.value
        return row


@dataclass(frozen=True, slots=True)
class FrontierDecision:
    disposition: FrontierDisposition
    facts: tuple[ContextFrontierFact, ...] = ()
    rendered: str = ""
    reason_codes: tuple[str, ...] = ()
    candidate_count: int = 0
    accounted_count: int = 0
    accounting: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "facts": [fact.as_dict() for fact in self.facts],
            "rendered": self.rendered,
            "reason_codes": list(self.reason_codes),
            "candidate_count": self.candidate_count,
            "accounted_count": self.accounted_count,
            "accounting": [dict(row) for row in self.accounting],
        }


def _mapping(evidence: RepositoryEvidence | Mapping[str, Any]) -> Mapping[str, Any]:
    return evidence.as_dict() if isinstance(evidence, RepositoryEvidence) else evidence


def _provider_text(messages: Sequence[Mapping[str, Any]]) -> str:
    pieces: list[str] = []
    for message in messages:
        pieces.append(str(message.get("content") or ""))
        for action in (message.get("extra") or {}).get("actions") or ():
            pieces.append(str(action.get("command") or action.get("cmd") or ""))
    return "\n".join(pieces).replace("\\", "/")


def _fact_id(*values: object) -> str:
    return hashlib.sha256("\0".join(map(str, values)).encode("utf-8", "replace")).hexdigest()[:20]


def _definition_candidates(
    evidence: Mapping[str, Any], source_revision: str
) -> list[ContextFrontierFact]:
    graph_revision = str(evidence.get("graph_revision") or "")
    anchors = {
        (str(item.get("path") or ""), str(item.get("symbol") or "")): item
        for item in evidence.get("anchors") or ()
        if isinstance(item, Mapping)
    }
    candidates: list[ContextFrontierFact] = []
    for item in evidence.get("definitions") or ():
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "").replace("\\", "/")
        symbol = str(item.get("symbol") or "")
        line = int(item.get("line") or 0)
        signature = str(item.get("signature") or "")
        anchor = anchors.get((path, symbol), {})
        certainty = float(item.get("semantic_certainty") or (1.0 if line > 0 else 0.0))
        relevance = float(
            item.get("retrieval_relevance")
            or anchor.get("retrieval_relevance")
            or anchor.get("confidence")
            or 0.0
        )
        candidates.append(
            ContextFrontierFact(
                _fact_id("definition", path, line, symbol, signature, source_revision),
                ContextFrontierKind.DEFINITION,
                path,
                line,
                symbol,
                signature,
                "defines",
                source_revision,
                graph_revision,
                certainty,
                relevance,
            )
        )
    return candidates


def _caller_candidates(
    evidence: Mapping[str, Any], source_revision: str
) -> list[ContextFrontierFact]:
    graph_revision = str(evidence.get("graph_revision") or "")
    candidates: list[ContextFrontierFact] = []
    for item in evidence.get("callers") or ():
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("caller_path") or "").replace("\\", "/")
        symbol = str(item.get("caller") or item.get("caller_symbol") or "")
        line = int(item.get("caller_line") or 0)
        target = str(item.get("target") or item.get("target_symbol") or "")
        certainty = float(item.get("confidence") or item.get("semantic_certainty") or 0.0)
        if str(item.get("semantics") or "") == "graph_recorded" and not certainty:
            certainty = 1.0
        candidates.append(
            ContextFrontierFact(
                _fact_id("caller", path, line, symbol, target, source_revision),
                ContextFrontierKind.CALLER,
                path,
                line,
                symbol,
                target,
                "calls",
                source_revision,
                graph_revision,
                certainty,
                1.0,
            )
        )
    return candidates


def _reference_candidates(
    evidence: Mapping[str, Any], source_revision: str
) -> list[ContextFrontierFact]:
    graph_revision = str(evidence.get("graph_revision") or "")
    candidates: list[ContextFrontierFact] = []
    for item in evidence.get("references") or ():
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "").replace("\\", "/")
        symbol = str(item.get("symbol") or "")
        line = int(item.get("line") or 0)
        certainty = float(item.get("semantic_certainty") or (1.0 if line > 0 else 0.0))
        kind = (
            ContextFrontierKind.TEST
            if bool(item.get("is_test")) or "test" in path.lower()
            else ContextFrontierKind.REFERENCE
        )
        candidates.append(
            ContextFrontierFact(
                _fact_id(kind.value, path, line, symbol, source_revision),
                kind,
                path,
                line,
                symbol,
                str(item.get("target") or ""),
                "references",
                source_revision,
                graph_revision,
                certainty,
                float(item.get("retrieval_relevance") or 1.0),
            )
        )
    return candidates


def _represented(fact: ContextFrontierFact, text: str) -> bool:
    if fact.kind is ContextFrontierKind.DEFINITION:
        return bool(fact.value and fact.value in text)
    anchors = [anchor for anchor in (fact.path, fact.symbol, fact.value) if anchor]
    return bool(anchors and all(anchor in text for anchor in anchors[:2]))


def _render_fact(fact: ContextFrontierFact) -> str:
    location = fact.path + (f":{fact.line}" if fact.line > 0 else "")
    if fact.kind is ContextFrontierKind.DEFINITION:
        detail = fact.value or fact.symbol
        return f"- Definition {location}: {detail}"
    if fact.kind is ContextFrontierKind.CALLER:
        return f"- Caller {location}: {fact.symbol} calls {fact.value}"
    if fact.kind in {ContextFrontierKind.REFERENCE, ContextFrontierKind.TEST}:
        return f"- {fact.kind.value.title()} {location}: {fact.symbol}"
    return f"- {fact.kind.value.title()} {location}: {fact.value or fact.symbol}"


def compile_incremental_frontier(
    evidence: RepositoryEvidence | Mapping[str, Any],
    messages: Sequence[Mapping[str, Any]],
    *,
    source_revision: str,
    delivered_fact_ids: frozenset[str] = frozenset(),
    max_facts: int = 3,
    max_chars: int = 1_200,
    certainty_threshold: float = 0.95,
    relevance_threshold: float = 0.95,
) -> FrontierDecision:
    """Select the smallest certified repository frame absent from provider history."""

    row = _mapping(evidence)
    status = str(row.get("status") or "")
    substrate_failures = [
        reason
        for reason, healthy in (
            (
                status or "repository_intelligence_unavailable",
                status == RepositoryIntelligenceStatus.HEALTHY_CURRENT.value,
            ),
            ("repository_evidence_unavailable", bool(row.get("available"))),
            ("repository_index_not_current", bool(row.get("index_current"))),
            ("repository_intelligence_not_valid", bool(row.get("intelligence_valid"))),
            ("repository_graph_revision_missing", bool(row.get("graph_revision"))),
        )
        if not healthy
    ]
    if substrate_failures:
        return FrontierDecision(
            FrontierDisposition.SUBSTRATE_FAILURE,
            reason_codes=tuple(dict.fromkeys(substrate_failures)),
        )
    evidence_revision = str(row.get("source_revision") or "")
    if evidence_revision and evidence_revision != source_revision:
        return FrontierDecision(
            FrontierDisposition.STALE_SOURCE_REVISION,
            reason_codes=("repository_source_revision_mismatch",),
        )

    candidates = [
        *_definition_candidates(row, source_revision),
        *_caller_candidates(row, source_revision),
        *_reference_candidates(row, source_revision),
    ]
    provider_text = _provider_text(messages)
    selected: list[ContextFrontierFact] = []
    accounting: list[dict[str, Any]] = []
    rendered_lines = [f"Repository intelligence at source revision {source_revision[:12]}:"]
    for fact in candidates:
        if fact.fact_id in delivered_fact_ids or _represented(fact, provider_text):
            disposition = FrontierDisposition.REPRESENTED_MESSAGE
        elif (
            fact.semantic_certainty < certainty_threshold
            or fact.retrieval_relevance < relevance_threshold
            or fact.line <= 0
        ):
            disposition = FrontierDisposition.LOW_PRECISION
        else:
            line = _render_fact(fact)
            if (
                len(selected) >= max(1, max_facts)
                or len("\n".join((*rendered_lines, line))) > max_chars
            ):
                disposition = FrontierDisposition.FRONTIER_BUDGET
            else:
                selected.append(fact)
                rendered_lines.append(line)
                disposition = FrontierDisposition.SELECTED_FRONTIER
        accounting.append(
            {
                "fact_id": fact.fact_id,
                "kind": fact.kind.value,
                "path": fact.path,
                "line": fact.line,
                "symbol": fact.symbol,
                "source_revision": fact.source_revision,
                "graph_revision": fact.graph_revision,
                "semantic_certainty": fact.semantic_certainty,
                "retrieval_relevance": fact.retrieval_relevance,
                "disposition": disposition.value,
            }
        )
    if selected:
        disposition = FrontierDisposition.SELECTED_FRONTIER
        rendered = "\n".join(rendered_lines)
        reasons = ("incremental_repository_frontier",)
    elif candidates and all(
        item["disposition"] == FrontierDisposition.REPRESENTED_MESSAGE.value for item in accounting
    ):
        disposition = FrontierDisposition.REPRESENTED_MESSAGE
        rendered = ""
        reasons = ("all_certified_facts_already_represented",)
    elif (
        candidates
        and all(
            item["disposition"]
            in {
                FrontierDisposition.REPRESENTED_MESSAGE.value,
                FrontierDisposition.FRONTIER_BUDGET.value,
            }
            for item in accounting
        )
        and any(
            item["disposition"] == FrontierDisposition.FRONTIER_BUDGET.value for item in accounting
        )
    ):
        disposition = FrontierDisposition.FRONTIER_BUDGET
        rendered = ""
        reasons = ("certified_frontier_exceeds_current_budget",)
    elif candidates:
        disposition = FrontierDisposition.LOW_PRECISION
        rendered = ""
        reasons = ("no_certified_incremental_fact",)
    else:
        disposition = FrontierDisposition.NO_FRONTIER
        rendered = ""
        reasons = ("repository_returned_no_structural_facts",)
    return FrontierDecision(
        disposition,
        tuple(selected),
        rendered,
        reasons,
        len(candidates),
        len(accounting),
        tuple(accounting),
    )


__all__ = [
    "ContextFrontierFact",
    "ContextFrontierKind",
    "FrontierDecision",
    "FrontierDisposition",
    "compile_incremental_frontier",
]
