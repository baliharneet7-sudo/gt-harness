"""Certified, bounded repository context projected at the provider seam.

This module is pure composition over GT's existing repository substrate.  It
does not parse source, invoke a model, execute a tool, or invent missing graph
edges.  Unknown, ambiguous, external, stale, or content-unbound relationships
remain ranking evidence and cannot enter execution or impact projections.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from typing import Any

from gt_engine.contributions import ContributionKind, GTContribution
from gt_engine.hybrid_retrieval import EvidenceOrigin, StructuralLink
from gt_engine.repository_intelligence import RepositoryEvidence
from gt_engine.semantic_evidence import (
    SemanticEvidenceBridge,
    SemanticEvidenceResult,
    SemanticEvidenceStatus,
)


class RepositoryContextStatus(StrEnum):
    DELIVER = "deliver"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True, order=True)
class SymbolRef:
    path: str
    symbol: str
    line: int

    @property
    def rendered(self) -> str:
        return f"{self.path}#{self.symbol}" if self.symbol else self.path


@dataclass(frozen=True, slots=True)
class DirectedExecutionStep:
    source: SymbolRef
    target: SymbolRef
    confidence: float
    provenance: tuple[str, ...]
    resolution_method: str = ""
    receiver_type: str = ""
    source_return_type: str = ""
    target_return_type: str = ""


@dataclass(frozen=True, slots=True)
class ExecutionView:
    view_id: str
    steps: tuple[DirectedExecutionStep, ...]
    truncated: bool = False
    cycle_terminated: bool = False
    entry_kind: str = "graph_root"
    route: str = ""

    @property
    def rendered(self) -> str:
        if not self.steps:
            return ""
        nodes = [self.steps[0].source.rendered]
        nodes.extend(step.target.rendered for step in self.steps)
        chain = " -> ".join(nodes)
        annotations = tuple(
            dict.fromkeys(
                annotation
                for step in self.steps
                for annotation in (
                    f"receiver={step.receiver_type}" if step.receiver_type else "",
                    (
                        f"resolution={step.resolution_method}"
                        if step.resolution_method
                        else ""
                    ),
                )
                if annotation
            )
        )
        suffix = f" [{'; '.join(annotations)}]" if annotations else ""
        route = f" route={self.route}" if self.route else ""
        return f"{chain}{route}{suffix}"


@dataclass(frozen=True, slots=True)
class ImpactFact:
    claim_id: str
    kind: str
    depth: int
    source: SymbolRef
    target: SymbolRef
    relation: str
    provenance: tuple[str, ...]

    @property
    def rendered(self) -> str:
        if self.kind == "caller":
            return (
                f"caller depth {self.depth}: {self.source.rendered} calls "
                f"{self.target.rendered}"
            )
        if self.kind == "test":
            return f"test: {self.target.rendered} asserts {self.source.rendered}"
        if self.kind == "api_consumer":
            return f"API consumer: {self.source.rendered} consumes {self.target.rendered}"
        if self.kind == "re_export":
            return f"re-export: {self.source.rendered} exports {self.target.rendered}"
        return (
            f"{self.kind}: {self.source.rendered} --{self.relation.lower()}--> "
            f"{self.target.rendered}"
        )


@dataclass(frozen=True, slots=True)
class DecisionOpportunity:
    kind: str
    evidence_action: int
    eligible_call: int
    source_revision: str
    graph_revision: str
    anchors: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    changed_symbols: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    source_revision: str
    graph_revision: str
    repository_evidence: RepositoryEvidence
    structural_links: tuple[StructuralLink, ...]
    diagnostics: tuple[str, ...] = ()
    validation_checks: tuple[str, ...] = ()
    represented_checks: frozenset[str] = frozenset()
    path_origins: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class DiagnosticFact:
    claim_id: str
    path: str
    line: int
    message: str

    @property
    def rendered(self) -> str:
        return f"- Observed diagnostic {self.path}:{self.line}: {self.message}"


@dataclass(frozen=True, slots=True)
class ValidationFact:
    claim_id: str
    command: str
    impacted_path: str

    @property
    def rendered(self) -> str:
        return f"- Validate impacted path {self.impacted_path} with: {self.command}"


@dataclass(frozen=True, slots=True)
class RepositoryContextProjection:
    status: RepositoryContextStatus
    contributions: tuple[GTContribution, ...]
    rendered_text: str
    claim_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    source_revision: str
    graph_revision: str
    execution_views: tuple[ExecutionView, ...] = ()
    impact_facts: tuple[ImpactFact, ...] = ()
    diagnostic_facts: tuple[DiagnosticFact, ...] = ()
    validation_facts: tuple[ValidationFact, ...] = ()
    semantic_evidence: SemanticEvidenceResult | None = None
    token_count: int = 0
    truncated_count: int = 0
    rejected_edge_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["status"] = self.status.value
        row["contributions"] = [asdict(item) for item in self.contributions]
        row["execution_views"] = [asdict(item) for item in self.execution_views]
        row["impact_facts"] = [asdict(item) for item in self.impact_facts]
        row["diagnostic_facts"] = [asdict(item) for item in self.diagnostic_facts]
        row["validation_facts"] = [asdict(item) for item in self.validation_facts]
        row["semantic_evidence"] = (
            self.semantic_evidence.as_dict() if self.semantic_evidence is not None else None
        )
        return row


_ELIGIBLE_KINDS = frozenset(
    {
        "post_read_search",
        "post_mutation",
        "post_diagnostic",
        "post_validation",
        "post_submit",
        "pre_submit",
        "diff",
    }
)
_IMPACT_RELATIONS = frozenset(
    {
        "ASSERTED_BY",
        "TESTED_BY",
        "IMPLEMENTS",
        "EXTENDS",
        "OVERRIDES",
        "HANDLES_ROUTE",
        "IMPORTS",
        "API_CALLS",
        "API_CALL",
        "REFERENCES",
        "RE_EXPORTS",
    }
)
_REVERSE_DEPENDENCY_RELATIONS = frozenset(
    {
        "API_CALL",
        "API_CALLS",
        "EXTENDS",
        "IMPLEMENTS",
        "IMPORTS",
        "OVERRIDES",
        "REFERENCES",
        "RE_EXPORTS",
    }
)


def _stable_id(prefix: str, *parts: str) -> str:
    material = "\0".join(str(part) for part in parts)
    return prefix + hashlib.sha256(material.encode("utf-8", "surrogatepass")).hexdigest()[:20]


def _tokens(value: str) -> int:
    return len(re.findall(r"\w+|[^\w\s]", str(value or ""), re.UNICODE))


def _path(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _node(source: bool, link: StructuralLink) -> SymbolRef:
    return SymbolRef(
        path=_path(link.source_path if source else link.target_path),
        symbol=str(link.source_symbol if source else link.target_symbol or "").strip(),
        line=max(1, int(link.source_start_line if source else link.target_start_line or 1)),
    )


def _certified(link: StructuralLink) -> bool:
    return bool(
        link.certified
        and link.origin == "program"
        and link.resolution_outcome == "exact"
        and float(link.confidence) >= 0.95
        and link.source_symbol
        and link.target_symbol
        and int(link.source_start_line or 0) > 0
        and int(link.target_start_line or 0) > 0
        and link.source_content_sha256
        and link.target_content_sha256
        and link.source_evidence_origin == EvidenceOrigin.PREEXISTING_REPOSITORY.value
        and link.target_evidence_origin == EvidenceOrigin.PREEXISTING_REPOSITORY.value
    )


class RepositoryContextEngine:
    """Project semantic, execution, and impact evidence through one interface."""

    def __init__(
        self,
        *,
        max_depth: int = 6,
        max_branching: int = 3,
        max_execution_views: int = 3,
        max_impact_facts: int = 8,
        max_tokens: int = 256,
    ) -> None:
        self.max_depth = max(1, int(max_depth))
        self.max_branching = max(1, int(max_branching))
        self.max_execution_views = max(1, int(max_execution_views))
        self.max_impact_facts = max(1, int(max_impact_facts))
        self.max_tokens = max(1, int(max_tokens))
        self._semantic = SemanticEvidenceBridge(max_items=6, max_tokens=max_tokens)

    @staticmethod
    def _matches(node: SymbolRef, paths: frozenset[str], symbols: frozenset[str]) -> bool:
        if symbols:
            return bool(node.symbol and node.symbol in symbols)
        return node.path in paths

    def _execution_views(
        self,
        links: tuple[StructuralLink, ...],
        anchor_paths: frozenset[str],
        anchor_symbols: frozenset[str],
    ) -> tuple[tuple[ExecutionView, ...], int]:
        calls = tuple(
            link for link in links if link.relation.upper() == "CALLS" and _certified(link)
        )
        rejected = sum(
            1
            for link in links
            if link.relation.upper() == "CALLS" and not _certified(link)
        )
        adjacency: dict[SymbolRef, list[tuple[SymbolRef, StructuralLink]]] = defaultdict(list)
        incoming: set[SymbolRef] = set()
        for link in calls:
            source, target = _node(True, link), _node(False, link)
            adjacency[source].append((target, link))
            incoming.add(target)
        for rows in adjacency.values():
            rows.sort(key=lambda row: (row[0].path.lower(), row[0].symbol, row[0].line))
        route_entries: dict[SymbolRef, str] = {}
        for link in links:
            if link.relation.upper() != "HANDLES_ROUTE" or not _certified(link):
                continue
            route_entries[_node(True, link)] = link.route
        entries = [
            (node, "route_entry", route_entries[node]) for node in sorted(route_entries)
        ]
        entries.extend(
            (node, "declared_main", "")
            for node in sorted(set(adjacency) - incoming)
            if node.symbol in {"main", "Main"} and node not in route_entries
        )
        entries.extend(
            (node, "graph_root", "")
            for node in sorted(set(adjacency) - incoming)
            if node not in route_entries and node.symbol not in {"main", "Main"}
        )
        if not entries:
            entries = [
                (node, "anchored_seed", "")
                for node in sorted(set(adjacency) | incoming)
                if self._matches(node, anchor_paths, anchor_symbols)
            ]

        views: list[ExecutionView] = []
        queue: deque[
            tuple[
                SymbolRef,
                tuple[DirectedExecutionStep, ...],
                frozenset[SymbolRef],
                str,
                str,
            ]
        ]
        queue = deque(
            (entry, (), frozenset({entry}), entry_kind, route)
            for entry, entry_kind, route in entries
        )
        while queue and len(views) < self.max_execution_views:
            current, steps, visited, entry_kind, route = queue.popleft()
            rows = adjacency.get(current, ())[: self.max_branching]
            expanded = False
            for target, link in rows:
                step = DirectedExecutionStep(
                    source=current,
                    target=target,
                    confidence=float(link.confidence),
                    provenance=tuple(link.provenance),
                    resolution_method=link.resolution_method,
                    receiver_type=link.receiver_type,
                    source_return_type=link.source_return_type,
                    target_return_type=link.target_return_type,
                )
                next_steps = (*steps, step)
                contains_anchor = any(
                    self._matches(node, anchor_paths, anchor_symbols)
                    for node in (next_steps[0].source, *(item.target for item in next_steps))
                )
                if target in visited:
                    if contains_anchor:
                        views.append(
                            ExecutionView(
                                _stable_id(
                                    "gt-execution-",
                                    *(
                                        s.source.rendered + ">" + s.target.rendered
                                        for s in next_steps
                                    ),
                                ),
                                next_steps,
                                cycle_terminated=True,
                                entry_kind=entry_kind,
                                route=route,
                            )
                        )
                    continue
                expanded = True
                terminal = len(next_steps) >= self.max_depth or not adjacency.get(target)
                if terminal:
                    if contains_anchor:
                        views.append(
                            ExecutionView(
                                _stable_id(
                                    "gt-execution-",
                                    *(
                                        s.source.rendered + ">" + s.target.rendered
                                        for s in next_steps
                                    ),
                                ),
                                next_steps,
                                truncated=len(next_steps) >= self.max_depth,
                                entry_kind=entry_kind,
                                route=route,
                            )
                        )
                else:
                    queue.append(
                        (target, next_steps, visited | {target}, entry_kind, route)
                    )
                if len(views) >= self.max_execution_views:
                    break
            if steps and not expanded:
                contains_anchor = any(
                    self._matches(node, anchor_paths, anchor_symbols)
                    for node in (steps[0].source, *(item.target for item in steps))
                )
                if contains_anchor and not any(view.steps == steps for view in views):
                    views.append(
                        ExecutionView(
                            _stable_id(
                                "gt-execution-",
                                *(
                                    s.source.rendered + ">" + s.target.rendered
                                    for s in steps
                                ),
                            ),
                            steps,
                            entry_kind=entry_kind,
                            route=route,
                        )
                    )
        unique = {view.view_id: view for view in views}
        return tuple(unique.values()), rejected

    def _impact(
        self,
        links: tuple[StructuralLink, ...],
        changed_paths: frozenset[str],
        changed_symbols: frozenset[str],
    ) -> tuple[tuple[ImpactFact, ...], int]:
        accepted = tuple(link for link in links if _certified(link))
        rejected = sum(
            1
            for link in links
            if link.relation.upper() in _IMPACT_RELATIONS
            and link.relation.upper() != "CALLS"
            and not _certified(link)
        )
        reverse_calls: dict[SymbolRef, list[tuple[SymbolRef, StructuralLink]]] = defaultdict(list)
        nodes: set[SymbolRef] = set()
        for link in accepted:
            source, target = _node(True, link), _node(False, link)
            nodes.update((source, target))
            if link.relation.upper() == "CALLS":
                reverse_calls[target].append((source, link))
        for rows in reverse_calls.values():
            rows.sort(key=lambda row: (row[0].path.lower(), row[0].symbol, row[0].line))
        seeds = sorted(
            node for node in nodes if self._matches(node, changed_paths, changed_symbols)
        )
        queue = deque((seed, 0) for seed in seeds)
        visited = set(seeds)
        facts: list[ImpactFact] = []
        while queue and len(facts) < self.max_impact_facts:
            target, depth = queue.popleft()
            if depth >= 3:
                continue
            for caller, link in reverse_calls.get(target, ()):
                claim = _stable_id(
                    "gt-impact-", "caller", str(depth + 1), caller.rendered, target.rendered
                )
                facts.append(
                    ImpactFact(
                        claim, "caller", depth + 1, caller, target, "CALLS", tuple(link.provenance)
                    )
                )
                if caller not in visited:
                    visited.add(caller)
                    queue.append((caller, depth + 1))
                if len(facts) >= self.max_impact_facts:
                    break

        for link in accepted:
            if len(facts) >= self.max_impact_facts:
                break
            relation = link.relation.upper()
            if relation not in _IMPACT_RELATIONS or relation == "CALLS":
                continue
            source, target = _node(True, link), _node(False, link)
            changed_endpoint = (
                target if relation in _REVERSE_DEPENDENCY_RELATIONS else source
            )
            if not self._matches(changed_endpoint, changed_paths, changed_symbols):
                continue
            kind = (
                "test"
                if relation in {"ASSERTED_BY", "TESTED_BY"}
                else "api_consumer"
                if relation in {"API_CALL", "API_CALLS"}
                else "re_export"
                if relation == "RE_EXPORTS"
                else relation.lower()
            )
            facts.append(
                ImpactFact(
                    _stable_id("gt-impact-", kind, source.rendered, relation, target.rendered),
                    kind,
                    1,
                    source,
                    target,
                    relation,
                    tuple(link.provenance),
                )
            )
        unique = {fact.claim_id: fact for fact in facts}
        return tuple(unique.values()), rejected

    @staticmethod
    def _preexisting_semantic_evidence(
        evidence: RepositoryEvidence,
        path_origins: tuple[tuple[str, str], ...],
    ) -> RepositoryEvidence:
        """Keep provider-visible semantic rows on task-start source only.

        Graph refreshes include model-authored files. Those rows remain useful
        to the controller, but must not become a new provider-visible claim.
        Missing origin binding is unknown and therefore terminal.
        """

        origins = {_path(path): str(origin) for path, origin in path_origins}

        def preexisting(path: Any) -> bool:
            return (
                origins.get(_path(path or ""))
                == EvidenceOrigin.PREEXISTING_REPOSITORY.value
            )

        def keep(rows: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
            return tuple(
                row
                for row in rows
                if preexisting(row.get("path"))
            )

        def keep_calls(rows: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
            return tuple(
                row
                for row in rows
                if preexisting(row.get("caller_path"))
                and preexisting(row.get("target_path"))
            )

        def keep_references(
            rows: tuple[dict[str, Any], ...]
        ) -> tuple[dict[str, Any], ...]:
            return tuple(
                row
                for row in rows
                if preexisting(row.get("path"))
                and preexisting(row.get("target_path"))
            )

        return replace(
            evidence,
            definitions=keep(evidence.definitions),
            references=keep_references(evidence.references),
            callers=keep_calls(evidence.callers),
            semantic_properties=keep(evidence.semantic_properties),
        )

    @staticmethod
    def _diagnostics(
        diagnostics: tuple[str, ...], anchor_paths: frozenset[str]
    ) -> tuple[DiagnosticFact, ...]:
        facts: dict[str, DiagnosticFact] = {}
        pattern = re.compile(
            r"(?P<path>(?:[A-Za-z]:)?[^\s:]+\.[A-Za-z0-9_]+):"
            r"(?P<line>\d+)(?::\d+)?:\s*(?P<message>[^\r\n]{1,240})"
        )
        for diagnostic in diagnostics:
            for match in pattern.finditer(str(diagnostic or "")):
                path = _path(match.group("path"))
                if anchor_paths:
                    matching_anchors = tuple(
                        anchor
                        for anchor in anchor_paths
                        if path == anchor or path.endswith("/" + anchor)
                    )
                    if len(matching_anchors) != 1:
                        continue
                    path = matching_anchors[0]
                line = int(match.group("line"))
                message = " ".join(match.group("message").split())
                claim_id = _stable_id("gt-diagnostic-", path, str(line), message)
                facts.setdefault(claim_id, DiagnosticFact(claim_id, path, line, message))
        return tuple(facts.values())

    @staticmethod
    def _validation(
        impact: tuple[ImpactFact, ...],
        checks: tuple[str, ...],
        represented_checks: frozenset[str],
    ) -> tuple[ValidationFact, ...]:
        facts: dict[str, ValidationFact] = {}
        test_paths = tuple(
            dict.fromkeys(fact.target.path for fact in impact if fact.kind == "test")
        )
        for path in test_paths:
            normalized_checks = tuple(
                " ".join(str(command or "").split()) for command in checks
            )
            specific_checks = tuple(
                command for command in normalized_checks if path in command
            )
            candidates = specific_checks or normalized_checks[:1]
            for normalized in candidates:
                if not normalized or normalized in represented_checks:
                    continue
                claim_id = _stable_id("gt-validation-", path, normalized)
                facts.setdefault(claim_id, ValidationFact(claim_id, normalized, path))
                break
        return tuple(facts.values())

    def _abstain(
        self,
        opportunity: DecisionOpportunity,
        reasons: tuple[str, ...],
        *,
        semantic: SemanticEvidenceResult | None = None,
        rejected_edge_count: int = 0,
    ) -> RepositoryContextProjection:
        return RepositoryContextProjection(
            status=RepositoryContextStatus.ABSTAIN,
            contributions=(),
            rendered_text="",
            claim_ids=(),
            reason_codes=reasons,
            source_revision=opportunity.source_revision,
            graph_revision=opportunity.graph_revision,
            semantic_evidence=semantic,
            rejected_edge_count=rejected_edge_count,
        )

    def project(
        self,
        opportunity: DecisionOpportunity,
        snapshot: RepositorySnapshot,
        *,
        delivered_claim_ids: frozenset[str] = frozenset(),
    ) -> RepositoryContextProjection:
        if opportunity.kind not in _ELIGIBLE_KINDS:
            return self._abstain(opportunity, ("ineligible_opportunity",))
        if (
            opportunity.source_revision != snapshot.source_revision
            or opportunity.graph_revision != snapshot.graph_revision
        ):
            return self._abstain(opportunity, ("stale_repository_snapshot",))

        anchor_paths = frozenset(
            _path(item)
            for item in (*opportunity.anchors, *opportunity.changed_paths)
            if _path(item)
        )
        anchor_symbols = frozenset(
            str(item).strip()
            for item in opportunity.changed_symbols
            if str(item).strip()
        )
        if opportunity.changed_paths and not anchor_symbols:
            anchor_symbols = frozenset(
                str(item.get("symbol") or "").strip()
                for item in snapshot.repository_evidence.definitions
                if _path(item.get("path") or "") in anchor_paths
                and str(item.get("symbol") or "").strip()
            )
        semantic_evidence = self._preexisting_semantic_evidence(
            snapshot.repository_evidence,
            snapshot.path_origins,
        )
        semantic = self._semantic.compose(
            semantic_evidence,
            source_revision=opportunity.source_revision,
            graph_revision=opportunity.graph_revision,
            delivered_claim_ids=delivered_claim_ids,
        )
        execution_views, rejected_edges = self._execution_views(
            snapshot.structural_links, anchor_paths, anchor_symbols
        )
        impact, rejected_impact_edges = self._impact(
            snapshot.structural_links, anchor_paths, anchor_symbols
        )
        rejected_edges += rejected_impact_edges
        diagnostics = self._diagnostics(snapshot.diagnostics, anchor_paths)
        validation = self._validation(
            impact,
            snapshot.validation_checks,
            snapshot.represented_checks,
        )

        lines: list[tuple[str, str]] = []
        if semantic.status is SemanticEvidenceStatus.DELIVER:
            lines.extend((item.claim_id, item.rendered) for item in semantic.items)
        for view in execution_views:
            lines.append(
                (
                    view.view_id,
                    f"- Execution (lower bound; {view.entry_kind}): {view.rendered}",
                )
            )
        lines.extend((fact.claim_id, f"- Impact {fact.rendered}") for fact in impact)
        lines.extend((fact.claim_id, fact.rendered) for fact in diagnostics)
        lines.extend((fact.claim_id, fact.rendered) for fact in validation)
        lines = [(claim, line) for claim, line in lines if claim not in delivered_claim_ids]
        if not lines:
            reasons = ["no_certified_repository_context"]
            if delivered_claim_ids and (
                semantic.reason_codes == ("semantic_evidence_already_delivered",)
                or execution_views
                or impact
            ):
                reasons = ["repository_context_already_delivered"]
            return self._abstain(
                opportunity,
                tuple(reasons),
                semantic=semantic,
                rejected_edge_count=rejected_edges,
            )

        heading = "Current certified repository context (lower bound):"
        selected: list[tuple[str, str]] = []
        used = _tokens(heading)
        truncated = 0
        for claim, line in lines:
            required = _tokens(line)
            if used + required > self.max_tokens:
                truncated += 1
                continue
            selected.append((claim, line))
            used += required
        if not selected:
            return self._abstain(
                opportunity,
                ("repository_context_token_budget",),
                semantic=semantic,
                rejected_edge_count=rejected_edges,
            )
        rendered = "\n".join((heading, *(line for _, line in selected)))
        claims = tuple(claim for claim, _ in selected)
        selected_claims = frozenset(claims)
        selected_semantic_items = tuple(
            item for item in semantic.items if item.claim_id in selected_claims
        )
        if selected_semantic_items != semantic.items:
            selected_semantic_rendered = (
                "\n".join(
                    (
                        "Certified semantic context "
                        "(source-backed; omitted facts may exist):",
                        *(item.rendered for item in selected_semantic_items),
                    )
                )
                if selected_semantic_items
                else ""
            )
            semantic = replace(
                semantic,
                status=(
                    SemanticEvidenceStatus.DELIVER
                    if selected_semantic_items
                    else SemanticEvidenceStatus.ABSTAIN
                ),
                items=selected_semantic_items,
                rendered_text=selected_semantic_rendered,
                claim_ids=tuple(item.claim_id for item in selected_semantic_items),
                reason_codes=tuple(
                    dict.fromkeys(
                        (*semantic.reason_codes, "repository_context_token_budget")
                    )
                ),
                token_count=_tokens(selected_semantic_rendered),
                truncated_count=(
                    semantic.truncated_count
                    + len(semantic.items)
                    - len(selected_semantic_items)
                ),
            )
        facts = tuple(
            _stable_id("gt-context-fact-", claim, opportunity.source_revision) for claim in claims
        )
        semantic_claims = {item.claim_id for item in semantic.items}
        execution_claims = {view.view_id for view in execution_views}
        impact_claims = {fact.claim_id for fact in impact}
        diagnostic_claims = {fact.claim_id for fact in diagnostics}
        validation_claims = {fact.claim_id for fact in validation}
        claim_metadata = tuple(
            {
                "claim_id": claim,
                "origin": (
                    "execution_observation"
                    if claim in diagnostic_claims
                    else EvidenceOrigin.PREEXISTING_REPOSITORY.value
                ),
                "authority": (
                    "execution_observation"
                    if claim in diagnostic_claims
                    else "certified_structural"
                    if claim in execution_claims or claim in impact_claims
                    else "compiler_semantic"
                    if claim in semantic_claims
                    else "declared_validation"
                    if claim in validation_claims
                    else "unknown"
                ),
                "materiality_reason": (
                    "current_attributable_failure"
                    if claim in diagnostic_claims
                    else "new_unresolved_task_obligation"
                    if claim in validation_claims
                    else "decision_relevant_repository_context"
                ),
                "source_revision": opportunity.source_revision,
                "graph_revision": opportunity.graph_revision,
            }
            for claim in claims
        )
        contribution = GTContribution.create(
            surface="repository_context",
            kind=ContributionKind.EVIDENCE,
            payload=rendered,
            claim_ids=claims,
            fact_ids=facts,
            evidence_action=opportunity.evidence_action,
            eligible_call=opportunity.eligible_call,
            source_revision=opportunity.source_revision,
            priority=18,
            claim_metadata=claim_metadata,
        )
        return RepositoryContextProjection(
            status=RepositoryContextStatus.DELIVER,
            contributions=(contribution,),
            rendered_text=rendered,
            claim_ids=claims,
            reason_codes=tuple(semantic.reason_codes),
            source_revision=opportunity.source_revision,
            graph_revision=opportunity.graph_revision,
            execution_views=tuple(
                view for view in execution_views if view.view_id in selected_claims
            ),
            impact_facts=tuple(
                fact for fact in impact if fact.claim_id in selected_claims
            ),
            diagnostic_facts=tuple(
                fact for fact in diagnostics if fact.claim_id in selected_claims
            ),
            validation_facts=tuple(
                fact for fact in validation if fact.claim_id in selected_claims
            ),
            semantic_evidence=semantic,
            token_count=_tokens(rendered),
            truncated_count=truncated,
            rejected_edge_count=rejected_edges,
        )


__all__ = [
    "DecisionOpportunity",
    "DiagnosticFact",
    "DirectedExecutionStep",
    "ExecutionView",
    "ImpactFact",
    "RepositoryContextEngine",
    "RepositoryContextProjection",
    "RepositoryContextStatus",
    "RepositorySnapshot",
    "SymbolRef",
    "ValidationFact",
]
