"""Graph-first persistent execution state for the central Mini-SWE runtime.

The repository graph is the fact authority.  A single optional model bootstrap
may select and order immutable catalog IDs; it cannot create repository facts.
After bootstrap, this module is a deterministic state-transition engine used at
provider, preflight, postflight, and graph-refresh boundaries.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from gt_engine.hybrid_retrieval import (
    HybridRetrievalResult,
    RepositoryDocument,
    StructuralLink,
)
from gt_engine.preflight import ActionOperation, ProposedAction
from gt_engine.repository_intelligence import RepositoryEvidence

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|[^\s]", re.UNICODE)
_PATH_RE = re.compile(r"(?<![\w.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+")
_CERTIFIED_RELATIONS = frozenset(
    {
        "calls",
        "called_by",
        "imports",
        "imported_by",
        "implements",
        "implemented_by",
        "inherits",
        "inherited_by",
        "overrides",
        "overridden_by",
        "references",
        "referenced_by",
        "test_assertion",
        "verified_closure",
    }
)
_CERTIFIED_RELATION_ALIASES = {
    "asserted_by": "test_assertion",
    "tested_by": "test_assertion",
    "calls_transitive": "verified_closure",
}


def _certified_relation(link: StructuralLink) -> str:
    if not link.certified:
        return ""
    normalized = str(link.relation or "").strip().lower()
    normalized = _CERTIFIED_RELATION_ALIASES.get(normalized, normalized)
    return normalized if normalized in _CERTIFIED_RELATIONS else ""


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "\0".join(str(part) for part in parts)
    return f"{prefix}-" + hashlib.sha256(payload.encode("utf-8", "surrogatepass")).hexdigest()[:20]


def _bounded(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    return text[:limit]


def _complete_excerpt(value: Any, limit: int = 1_200) -> str:
    """Return complete source lines within a fixed byte-independent bound."""

    selected: list[str] = []
    used = 0
    for line in str(value or "").replace("\x00", "").splitlines():
        required = len(line) + (1 if selected else 0)
        if used + required > max(0, int(limit)):
            break
        selected.append(line)
        used += required
    return "\n".join(selected).strip()


def _path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if raw.startswith("/app/"):
        raw = raw[5:]
    while raw.startswith("./"):
        raw = raw[2:]
    normalized = posixpath.normpath(raw) if raw else ""
    return "" if normalized in {"", ".", ".."} or normalized.startswith("../") else normalized


def _default_token_counter(text: str) -> int:
    """Deterministic packing unit; provider-side accounting remains authoritative."""

    return len(_TOKEN_RE.findall(str(text or "")))


class StateFieldAuthority(StrEnum):
    IMMUTABLE_INPUT = "immutable_input"
    DETERMINISTIC_DERIVED = "deterministic_derived"
    GENERATIVE_BOOTSTRAP = "generative_bootstrap"
    DETERMINISTIC_MUTABLE = "deterministic_mutable"
    EXECUTOR_OBSERVED = "executor_observed"


class CatalogItemKind(StrEnum):
    FOCUS = "focus"
    DEPENDENCY = "dependency"
    VALIDATION = "validation"
    DELIVERABLE = "deliverable"


class BootstrapStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    SELECTED = "selected"
    INVALID_FALLBACK = "invalid_fallback"
    ERROR_FALLBACK = "error_fallback"
    NOT_APPLICABLE = "not_applicable"


class StatePhase(StrEnum):
    LOCALIZING = "localizing"
    IMPLEMENTING = "implementing"
    VALIDATING = "validating"
    READY_TO_SUBMIT = "ready_to_submit"


class ObligationStatus(StrEnum):
    OPEN = "open"
    SATISFIED = "satisfied"
    INVALIDATED = "invalidated"


class StateValidationStatus(StrEnum):
    UNKNOWN = "unknown"
    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"


class ContextFrameKind(StrEnum):
    NONE = "none"
    INITIAL = "initial"
    CORE = "core"
    DELTA = "delta"
    CRITICAL = "critical"


PERSISTENT_STATE_FIELD_AUTHORITIES: dict[str, StateFieldAuthority] = {
    "state_id": StateFieldAuthority.DETERMINISTIC_DERIVED,
    "task_digest": StateFieldAuthority.IMMUTABLE_INPUT,
    "source_revision": StateFieldAuthority.DETERMINISTIC_MUTABLE,
    "graph_source_revision": StateFieldAuthority.DETERMINISTIC_MUTABLE,
    "graph_revision": StateFieldAuthority.DETERMINISTIC_MUTABLE,
    "graph_current": StateFieldAuthority.DETERMINISTIC_MUTABLE,
    "phase": StateFieldAuthority.DETERMINISTIC_MUTABLE,
    "bootstrap_status": StateFieldAuthority.DETERMINISTIC_DERIVED,
    "primary_focus_id": StateFieldAuthority.GENERATIVE_BOOTSTRAP,
    "ordered_item_ids": StateFieldAuthority.GENERATIVE_BOOTSTRAP,
    "risk_item_ids": StateFieldAuthority.GENERATIVE_BOOTSTRAP,
    "validation_item_ids": StateFieldAuthority.GENERATIVE_BOOTSTRAP,
    "current_focus_id": StateFieldAuthority.DETERMINISTIC_MUTABLE,
    "current_focus_path": StateFieldAuthority.EXECUTOR_OBSERVED,
    "files_inspected": StateFieldAuthority.EXECUTOR_OBSERVED,
    "files_modified": StateFieldAuthority.EXECUTOR_OBSERVED,
    "obligations": StateFieldAuthority.DETERMINISTIC_MUTABLE,
    "validation": StateFieldAuthority.EXECUTOR_OBSERVED,
    "current_failure": StateFieldAuthority.EXECUTOR_OBSERVED,
}


@dataclass(frozen=True, slots=True)
class BootstrapCatalogItem:
    item_id: str
    kind: CatalogItemKind
    label: str
    path: str = ""
    symbol: str = ""
    relation: str = ""
    anchors: tuple[str, ...] = ()
    required: bool = False
    certified: bool = True
    authority: StateFieldAuthority = StateFieldAuthority.DETERMINISTIC_DERIVED
    retrieval_rank: int = 0
    support_channels: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    source_start_line: int = 0
    source_end_line: int = 0
    source_claim_id: str = ""
    source_excerpt: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "kind": self.kind.value,
            "label": self.label,
            "path": self.path,
            "symbol": self.symbol,
            "relation": self.relation,
            "anchors": list(self.anchors),
            "required": self.required,
            "certified": self.certified,
            "authority": self.authority.value,
            "retrieval_rank": self.retrieval_rank,
            "support_channels": list(self.support_channels),
            "provenance": list(self.provenance),
            "source_start_line": self.source_start_line,
            "source_end_line": self.source_end_line,
            "source_claim_id": self.source_claim_id,
        }


@dataclass(frozen=True, slots=True)
class BootstrapCatalog:
    source_revision: str
    graph_source_revision: str
    graph_revision: str
    items: tuple[BootstrapCatalogItem, ...]
    complete: bool
    reason_codes: tuple[str, ...] = ()

    @property
    def item_ids(self) -> frozenset[str]:
        return frozenset(item.item_id for item in self.items)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "gt.persistent_bootstrap_catalog.v1",
            "source_revision": self.source_revision,
            "graph_source_revision": self.graph_source_revision,
            "graph_revision": self.graph_revision,
            "complete": self.complete,
            "reason_codes": list(self.reason_codes),
            "items": [item.as_dict() for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class BootstrapSelection:
    valid: bool
    primary_focus_id: str = ""
    ordered_item_ids: tuple[str, ...] = ()
    risk_item_ids: tuple[str, ...] = ()
    validation_item_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "primary_focus_id": self.primary_focus_id,
            "ordered_item_ids": list(self.ordered_item_ids),
            "risk_item_ids": list(self.risk_item_ids),
            "validation_item_ids": list(self.validation_item_ids),
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class StateObligation:
    obligation_id: str
    kind: str
    path: str
    relation: str
    source_path: str
    blocking: bool = False
    status: ObligationStatus = ObligationStatus.OPEN
    opened_revision: str = ""
    satisfied_revision: str = ""
    authority: StateFieldAuthority = StateFieldAuthority.DETERMINISTIC_MUTABLE

    def as_dict(self) -> dict[str, Any]:
        return {
            "obligation_id": self.obligation_id,
            "kind": self.kind,
            "path": self.path,
            "relation": self.relation,
            "source_path": self.source_path,
            "blocking": self.blocking,
            "status": self.status.value,
            "opened_revision": self.opened_revision,
            "satisfied_revision": self.satisfied_revision,
            "authority": self.authority.value,
        }


@dataclass(frozen=True, slots=True)
class StateValidation:
    status: StateValidationStatus = StateValidationStatus.UNKNOWN
    command: str = ""
    source_revision: str = ""
    action_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "command": self.command,
            "source_revision": self.source_revision,
            "action_id": self.action_id,
        }


@dataclass(frozen=True, slots=True)
class StateFailure:
    action_id: str
    operation: str
    diagnostic: str
    source_revision: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "operation": self.operation,
            "diagnostic": self.diagnostic,
            "source_revision": self.source_revision,
        }


@dataclass(frozen=True, slots=True)
class PersistentExecutionState:
    state_id: str
    task_digest: str
    version: int
    source_revision: str
    graph_source_revision: str
    graph_revision: str
    graph_current: bool
    phase: StatePhase
    bootstrap_status: BootstrapStatus
    primary_focus_id: str = ""
    current_focus_id: str = ""
    current_focus_path: str = ""
    ordered_item_ids: tuple[str, ...] = ()
    risk_item_ids: tuple[str, ...] = ()
    validation_item_ids: tuple[str, ...] = ()
    files_inspected: tuple[str, ...] = ()
    files_modified: tuple[str, ...] = ()
    obligations: tuple[StateObligation, ...] = ()
    validation: StateValidation = StateValidation()
    current_failure: StateFailure | None = None
    last_transition: str = "initialized"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "gt.persistent_execution_state.v1",
            "state_id": self.state_id,
            "task_digest": self.task_digest,
            "version": self.version,
            "source_revision": self.source_revision,
            "graph_source_revision": self.graph_source_revision,
            "graph_revision": self.graph_revision,
            "graph_current": self.graph_current,
            "phase": self.phase.value,
            "bootstrap_status": self.bootstrap_status.value,
            "primary_focus_id": self.primary_focus_id,
            "current_focus_id": self.current_focus_id,
            "current_focus_path": self.current_focus_path,
            "ordered_item_ids": list(self.ordered_item_ids),
            "risk_item_ids": list(self.risk_item_ids),
            "validation_item_ids": list(self.validation_item_ids),
            "files_inspected": list(self.files_inspected),
            "files_modified": list(self.files_modified),
            "obligations": [item.as_dict() for item in self.obligations],
            "validation": self.validation.as_dict(),
            "current_failure": (
                self.current_failure.as_dict() if self.current_failure is not None else None
            ),
            "last_transition": self.last_transition,
            "field_authority": {
                key: value.value for key, value in PERSISTENT_STATE_FIELD_AUTHORITIES.items()
            },
        }


@dataclass(frozen=True, slots=True)
class PreflightStateProjection:
    action_id: str
    considered: bool
    operation: str
    target_paths: tuple[str, ...]
    open_obligation_ids: tuple[str, ...]
    blocking_obligation_ids: tuple[str, ...]
    material_contradiction: bool
    reason_codes: tuple[str, ...]
    state_version: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "considered": self.considered,
            "operation": self.operation,
            "target_paths": list(self.target_paths),
            "open_obligation_ids": list(self.open_obligation_ids),
            "blocking_obligation_ids": list(self.blocking_obligation_ids),
            "material_contradiction": self.material_contradiction,
            "reason_codes": list(self.reason_codes),
            "state_version": self.state_version,
        }


@dataclass(frozen=True, slots=True)
class PersistentContextFrame:
    kind: ContextFrameKind
    rendered_text: str
    claim_ids: tuple[str, ...]
    state_version: int
    source_revision: str
    provider_call: int
    token_count: int
    reason_codes: tuple[str, ...] = ()
    selected_evidence: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "rendered_text": self.rendered_text,
            "claim_ids": list(self.claim_ids),
            "state_version": self.state_version,
            "source_revision": self.source_revision,
            "provider_call": self.provider_call,
            "token_count": self.token_count,
            "reason_codes": list(self.reason_codes),
            "selected_evidence": [dict(item) for item in self.selected_evidence],
        }


def _catalog_item(
    kind: CatalogItemKind,
    label: str,
    *,
    path: str = "",
    symbol: str = "",
    relation: str = "",
    anchors: Iterable[str] = (),
    required: bool = False,
    certified: bool = True,
    retrieval_rank: int = 0,
    support_channels: tuple[str, ...] = (),
    provenance: tuple[str, ...] = (),
    source_start_line: int = 0,
    source_end_line: int = 0,
    source_claim_id: str = "",
    source_excerpt: str = "",
) -> BootstrapCatalogItem:
    normalized_path = _path(path)
    normalized_anchors = tuple(
        dict.fromkeys(_bounded(anchor, 240) for anchor in anchors if _bounded(anchor, 240))
    )
    clean_label = _bounded(label, 280)
    item_id = _stable_id(
        "pes",
        kind.value,
        normalized_path,
        _bounded(symbol, 160),
        _bounded(relation, 80),
        clean_label,
        *normalized_anchors,
    )
    return BootstrapCatalogItem(
        item_id=item_id,
        kind=kind,
        label=clean_label,
        path=normalized_path,
        symbol=_bounded(symbol, 160),
        relation=_bounded(relation, 80),
        anchors=normalized_anchors,
        required=bool(required),
        certified=bool(certified),
        retrieval_rank=max(0, int(retrieval_rank)),
        support_channels=tuple(
            dict.fromkeys(_bounded(channel, 40) for channel in support_channels if channel)
        ),
        provenance=tuple(dict.fromkeys(_bounded(item, 160) for item in provenance if item))[:16],
        source_start_line=max(0, int(source_start_line)),
        source_end_line=max(0, int(source_end_line)),
        source_claim_id=str(source_claim_id or ""),
        source_excerpt=_complete_excerpt(source_excerpt),
    )


def build_bootstrap_catalog(
    *,
    instruction: str,
    evidence: RepositoryEvidence,
    documents: tuple[RepositoryDocument, ...],
    structural_links: tuple[StructuralLink, ...],
    source_revision: str,
    graph_revision: str,
    repository_complete: bool,
    graph_source_revision: str | None = None,
    explicit_checks: tuple[str, ...] = (),
    task_deliverables: tuple[str, ...] = (),
    initial_retrieval: HybridRetrievalResult | None = None,
    max_items: int = 32,
) -> BootstrapCatalog:
    """Build the immutable selection surface after a complete graph exists."""

    bound_graph_source_revision = str(graph_source_revision or source_revision)
    reasons: list[str] = []
    if not repository_complete:
        reasons.append("repository_corpus_incomplete")
    if not evidence.substrate_ready:
        reasons.append("repository_substrate_not_ready")
    if not source_revision or not graph_revision:
        reasons.append("revision_missing")
    if evidence.source_revision and evidence.source_revision != bound_graph_source_revision:
        reasons.append("evidence_source_revision_mismatch")
    if reasons:
        return BootstrapCatalog(
            source_revision=source_revision,
            graph_source_revision=bound_graph_source_revision,
            graph_revision=graph_revision,
            items=(),
            complete=False,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )

    candidates: dict[str, tuple[int, BootstrapCatalogItem]] = {}

    def add(priority: int, item: BootstrapCatalogItem) -> None:
        prior = candidates.get(item.item_id)
        if prior is None or priority < prior[0]:
            candidates[item.item_id] = (priority, item)

    for command in explicit_checks:
        clean = _bounded(command, 280)
        if clean:
            add(
                0,
                _catalog_item(
                    CatalogItemKind.VALIDATION,
                    f"Required validation: {clean}",
                    anchors=(clean,),
                    required=True,
                ),
            )
    for command in evidence.project_checks:
        clean = _bounded(command, 280)
        if clean and clean not in explicit_checks:
            add(
                4,
                _catalog_item(
                    CatalogItemKind.VALIDATION,
                    f"Project validation candidate: {clean}",
                    anchors=(clean,),
                    required=False,
                ),
            )
    for raw_path in task_deliverables:
        normalized = _path(raw_path)
        if normalized:
            add(
                0,
                _catalog_item(
                    CatalogItemKind.DELIVERABLE,
                    f"Required deliverable: {normalized}",
                    path=normalized,
                    anchors=(normalized,),
                    required=True,
                ),
            )

    for row in (*evidence.anchors, *evidence.definitions):
        path = _path(row.get("path"))
        symbol = _bounded(row.get("symbol"), 160)
        if not path:
            continue
        line = max(1, int(row.get("line") or row.get("start_line") or 1))
        anchor = f"{path}:{line}" + (f"#{symbol}" if symbol else "")
        add(
            1,
            _catalog_item(
                CatalogItemKind.FOCUS,
                f"Candidate implementation {anchor}",
                path=path,
                symbol=symbol,
                anchors=(anchor,),
            ),
        )

    for row in evidence.callers:
        path = _path(row.get("path"))
        symbol = _bounded(row.get("symbol"), 160)
        if path:
            add(
                2,
                _catalog_item(
                    CatalogItemKind.DEPENDENCY,
                    f"Certified caller {path}" + (f"#{symbol}" if symbol else ""),
                    path=path,
                    symbol=symbol,
                    relation="calls",
                    anchors=(path, symbol),
                ),
            )

    documents_by_path: dict[str, list[RepositoryDocument]] = {}
    for document in documents:
        documents_by_path.setdefault(_path(document.path), []).append(document)
    document_by_path = {
        path: path_documents[0]
        for path, path_documents in documents_by_path.items()
        if path_documents
    }

    def source_document(item: BootstrapCatalogItem) -> RepositoryDocument | None:
        path_documents = documents_by_path.get(item.path, ())
        wanted_symbol = _bounded(item.symbol, 160)
        if wanted_symbol:
            exact = next(
                (
                    document
                    for document in path_documents
                    if _bounded(document.symbol, 160) == wanted_symbol
                ),
                None,
            )
            if exact is not None:
                return exact
        return path_documents[0] if len(path_documents) == 1 else None

    # The accepted HybridRetriever is the task-localization authority shared
    # with the live provider-boundary path.  Its ranking is not a certified
    # claim that a file must be changed; it is a bounded set of current-checkout
    # candidates from which the single bootstrap call may select.  Source
    # identity is mechanical, while relevance remains explicitly ranked.
    if initial_retrieval is not None:
        if not initial_retrieval.query_hash:
            reasons.append("initial_retrieval_query_missing")
        for rank, ranked in enumerate(initial_retrieval.ranked_files[:16], start=1):
            candidate = ranked.representative
            normalized = _path(candidate.path)
            if (
                not normalized
                or normalized not in document_by_path
                or candidate.source_revision != bound_graph_source_revision
            ):
                continue
            if any(
                item.kind is CatalogItemKind.FOCUS
                and item.path == normalized
                and item.symbol == _bounded(candidate.symbol, 160)
                for _, item in candidates.values()
            ):
                continue
            line = max(1, int(candidate.start_line or 1))
            symbol = _bounded(candidate.symbol, 160)
            anchor = f"{normalized}:{line}" + (f"#{symbol}" if symbol else "")
            channels = tuple(channel.value for channel, _ in ranked.channel_ranks)
            add(
                min(30, 1 + rank),
                _catalog_item(
                    CatalogItemKind.FOCUS,
                    f"Hybrid-ranked repository candidate #{rank}: {anchor}",
                    path=normalized,
                    symbol=symbol,
                    anchors=(anchor,),
                    certified=False,
                    retrieval_rank=rank,
                    support_channels=channels,
                    provenance=tuple(
                        dict.fromkeys(
                            (
                                *candidate.provenance,
                                *ranked.provenance,
                                "hybrid_ranked_candidate",
                            )
                        )
                    ),
                ),
            )
    focus_paths = {
        item.path
        for _, item in candidates.values()
        if item.kind is CatalogItemKind.FOCUS and item.path
    }
    for link in structural_links:
        normalized_relation = _certified_relation(link)
        if not normalized_relation:
            continue
        if link.source_path not in focus_paths and link.target_path not in focus_paths:
            continue
        for path, symbol, role in (
            (link.source_path, link.source_symbol, "source"),
            (link.target_path, link.target_symbol, "target"),
        ):
            normalized = _path(path)
            if not normalized or normalized not in document_by_path:
                continue
            add(
                3,
                _catalog_item(
                    CatalogItemKind.DEPENDENCY,
                    f"Certified {normalized_relation} {role}: {normalized}"
                    + (f"#{symbol}" if symbol else ""),
                    path=normalized,
                    symbol=_bounded(symbol, 160),
                    relation=normalized_relation,
                    anchors=(normalized, _bounded(symbol, 160)),
                ),
            )

    # Exact task paths may seed a graph-backed focus even when task-conditioned
    # evidence is empty.  The path must exist in the certified corpus.
    for match in _PATH_RE.finditer(str(instruction or "").replace("\\", "/")):
        normalized = _path(match.group(0))
        document = document_by_path.get(normalized)
        if document is None:
            continue
        add(
            1,
            _catalog_item(
                CatalogItemKind.FOCUS,
                f"Task-named repository path: {normalized}",
                path=normalized,
                symbol=_bounded(document.symbol, 160),
                anchors=(normalized,),
            ),
        )

    # Source bytes never enter the bootstrap selection request. They remain in
    # the immutable host-owned catalog so a valid selected ID can be resolved
    # to exactly one checkout-backed span for the first executor request.
    enriched: dict[str, tuple[int, BootstrapCatalogItem]] = {}
    for item_id, (priority, item) in candidates.items():
        document = source_document(item)
        if document is None or not item.path:
            enriched[item_id] = (priority, item)
            continue
        excerpt = _complete_excerpt(document.text)
        start_line = max(1, int(document.start_line or 1))
        end_line = max(start_line, int(document.end_line or start_line))
        claim_id = (
            _stable_id(
                "bootstrap-source",
                item.path,
                str(start_line),
                str(end_line),
                item.symbol,
                excerpt,
            )
            if excerpt
            else ""
        )
        enriched[item_id] = (
            priority,
            replace(
                item,
                source_start_line=start_line,
                source_end_line=end_line,
                source_claim_id=claim_id,
                source_excerpt=excerpt,
            ),
        )
    candidates = enriched

    ordered = sorted(
        candidates.values(),
        key=lambda row: (
            row[0],
            not row[1].required,
            row[1].path,
            row[1].symbol,
            row[1].relation,
            row[1].item_id,
        ),
    )
    items = tuple(item for _, item in ordered[: max(1, int(max_items))])
    return BootstrapCatalog(
        source_revision=source_revision,
        graph_source_revision=bound_graph_source_revision,
        graph_revision=graph_revision,
        items=items,
        complete=bool(items) and not reasons,
        reason_codes=tuple(dict.fromkeys(reasons or (() if items else ("empty_catalog",)))),
    )


def parse_bootstrap_selection(
    raw: str,
    catalog: BootstrapCatalog,
    *,
    visible_item_ids: frozenset[str] | None = None,
) -> BootstrapSelection:
    """Accept only catalog identifiers from the model's JSON transport value."""

    if not catalog.complete:
        return BootstrapSelection(False, reason_codes=("catalog_incomplete",))
    try:
        value = json.loads(str(raw or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return BootstrapSelection(False, reason_codes=("invalid_json",))
    if not isinstance(value, dict):
        return BootstrapSelection(False, reason_codes=("invalid_shape",))
    allowed_keys = {
        "primary_focus_id",
        "ordered_item_ids",
        "risk_item_ids",
        "validation_item_ids",
    }
    if set(value) - allowed_keys:
        return BootstrapSelection(False, reason_codes=("unknown_field",))

    def ids(key: str, limit: int) -> tuple[str, ...] | None:
        raw_ids = value.get(key, [])
        if not isinstance(raw_ids, list) or not all(isinstance(item, str) for item in raw_ids):
            return None
        result = tuple(dict.fromkeys(item for item in raw_ids if item))
        return result if len(result) <= limit else None

    primary = value.get("primary_focus_id", "")
    ordered = ids("ordered_item_ids", 16)
    risks = ids("risk_item_ids", 8)
    validations = ids("validation_item_ids", 8)
    if not isinstance(primary, str) or ordered is None or risks is None or validations is None:
        return BootstrapSelection(False, reason_codes=("invalid_shape",))
    referenced = tuple(
        dict.fromkeys((primary, *(ordered or ()), *(risks or ()), *(validations or ())))
    )
    if any(item and item not in catalog.item_ids for item in referenced):
        return BootstrapSelection(False, reason_codes=("unknown_catalog_id",))
    if visible_item_ids is not None and any(
        item and item not in visible_item_ids for item in referenced
    ):
        return BootstrapSelection(False, reason_codes=("unshown_catalog_id",))
    item_by_id = {item.item_id: item for item in catalog.items}
    if any(item_by_id[item].kind is not CatalogItemKind.VALIDATION for item in validations):
        return BootstrapSelection(False, reason_codes=("invalid_validation_id",))
    if primary and item_by_id[primary].kind is CatalogItemKind.VALIDATION:
        return BootstrapSelection(False, reason_codes=("invalid_primary_focus",))
    return BootstrapSelection(
        True,
        primary_focus_id=primary,
        ordered_item_ids=ordered or (),
        risk_item_ids=risks or (),
        validation_item_ids=validations or (),
    )


def deterministic_bootstrap_fallback(
    catalog: BootstrapCatalog,
    *,
    status: BootstrapStatus = BootstrapStatus.INVALID_FALLBACK,
) -> tuple[BootstrapSelection, BootstrapStatus]:
    # A malformed/timed-out generative selection cannot authorize a ranked
    # repository focus. Preserve only explicit task requirements internally;
    # compile_context remains fail-open until a valid selection exists.
    primary = ""
    ordered = tuple(
        item.item_id for item in catalog.items if item.required or item.item_id == primary
    )
    validations = tuple(
        item.item_id for item in catalog.items if item.kind is CatalogItemKind.VALIDATION
    )
    return (
        BootstrapSelection(
            valid=False,
            primary_focus_id=primary,
            ordered_item_ids=ordered[:16],
            validation_item_ids=validations[:8],
            reason_codes=(status.value,),
        ),
        status,
    )


def build_bootstrap_messages(
    *,
    task: str,
    catalog: BootstrapCatalog,
    max_input_tokens: int = 2_000,
) -> list[dict[str, str]]:
    """Create a bounded one-call selection request using Mini-SWE's Bash envelope."""

    compact_items = [
        {
            "id": item.item_id,
            "kind": item.kind.value,
            "label": item.label,
            "required": item.required,
        }
        for item in catalog.items
    ]
    system = (
        "You select an execution focus from repository-certified entities and explicitly "
        "labeled hybrid-ranked candidates. Candidate relevance is not a requirement. "
        "You may order IDs but may not add facts, paths, symbols, or commands. "
        "The bash tool is a JSON transport only and will not execute."
    )

    def render_user(items: list[dict[str, Any]], task_excerpt: str) -> str:
        return (
            "TASK\n"
            + task_excerpt
            + "\n\nCERTIFIED CATALOG\n"
            + json.dumps(items, sort_keys=True, separators=(",", ":"))
            + "\n\nSelect only catalog IDs. Return exactly one bash tool call. Its command "
            "must be JSON with primary_focus_id, ordered_item_ids, risk_item_ids, "
            "and validation_item_ids. An empty primary_focus_id is allowed when the "
            "ranked candidates do not justify a focus. Do not emit shell code."
        )

    task_excerpt = _bounded(task, 1_200)
    user = render_user(compact_items, task_excerpt)
    # Fixed byte ceiling is an independent transport bound, not a token estimate.
    # One UTF-8 byte is a conservative upper bound on one provider token.  The
    # byte ceiling therefore makes the declared input-token limit true even
    # when the exact tokenizer is unavailable at catalog construction time.
    byte_ceiling = max(1_024, int(max_input_tokens))
    selected_items = list(compact_items)
    task_limits = (1_200, 600, 300, 0)
    for task_limit in task_limits:
        candidate_task = task_excerpt[:task_limit]
        user = render_user(selected_items, candidate_task)
        if len(system.encode("utf-8")) + len(user.encode("utf-8")) <= byte_ceiling:
            break
    else:
        candidate_task = task_excerpt[:300]
        while selected_items:
            selected_items.pop()
            user = render_user(selected_items, candidate_task)
            if len(system.encode("utf-8")) + len(user.encode("utf-8")) <= byte_ceiling:
                break
    return [
        {
            "role": "system",
            "content": system,
        },
        {"role": "user", "content": user},
    ]


def bootstrap_visible_item_ids(messages: list[dict[str, str]]) -> frozenset[str]:
    """Recover the exact ID authority surface carried by a bootstrap request."""

    if not messages:
        return frozenset()
    content = str(messages[-1].get("content") or "")
    try:
        payload = content.split("CERTIFIED CATALOG\n", 1)[1].split("\n\nSelect only", 1)[0]
        rows = json.loads(payload)
    except (IndexError, TypeError, ValueError, json.JSONDecodeError):
        return frozenset()
    if not isinstance(rows, list):
        return frozenset()
    return frozenset(
        str(row.get("id") or "")
        for row in rows
        if isinstance(row, dict) and str(row.get("id") or "")
    )


class PersistentExecutionStateEngine:
    """Task-scoped deterministic controller around one immutable bootstrap catalog."""

    def __init__(
        self,
        *,
        task: str,
        catalog: BootstrapCatalog,
        structural_links: tuple[StructuralLink, ...],
        present_paths: tuple[str, ...],
        workspace_root: str = "/app",
    ) -> None:
        task_digest = hashlib.sha256(str(task or "").encode("utf-8")).hexdigest()
        self._catalog = catalog
        self._workspace_root = posixpath.normpath(str(workspace_root or "/app").replace("\\", "/"))
        self._links = self._certified_links(structural_links)
        self._present_paths = frozenset(
            self._state_path(item) for item in present_paths if self._state_path(item)
        )
        self._snapshot = PersistentExecutionState(
            state_id=_stable_id("state", task_digest, catalog.source_revision),
            task_digest=task_digest,
            version=1,
            source_revision=catalog.source_revision,
            graph_revision=catalog.graph_revision,
            graph_source_revision=catalog.graph_source_revision,
            graph_current=True,
            phase=StatePhase.LOCALIZING,
            bootstrap_status=BootstrapStatus.NOT_REQUESTED,
            obligations=tuple(
                StateObligation(
                    obligation_id=_stable_id("obligation", item.kind.value, item.item_id),
                    kind=(
                        "produce_deliverable"
                        if item.kind is CatalogItemKind.DELIVERABLE
                        else "run_validation"
                    ),
                    path=item.path,
                    relation="task_requirement",
                    source_path=(item.anchors[0] if item.anchors else item.label),
                    blocking=True,
                    opened_revision=catalog.source_revision,
                )
                for item in catalog.items
                if item.required
                and item.kind in {CatalogItemKind.DELIVERABLE, CatalogItemKind.VALIDATION}
            ),
        )
        self._metrics: dict[str, int] = {
            "initializations": 1,
            "bootstrap_applications": 0,
            "context_compilations": 0,
            "preflight_projections": 0,
            "postflight_commits": 0,
            "graph_rebases": 0,
            "material_transitions": 0,
            "stale_rejections": 0,
        }
        self._receipts: list[dict[str, Any]] = []
        self._last_compiled_version = 0
        self._record("initialize", source_revision=catalog.source_revision)

    @classmethod
    def initialize_from_graph(
        cls,
        *,
        task: str,
        catalog: BootstrapCatalog,
        structural_links: tuple[StructuralLink, ...],
        present_paths: tuple[str, ...],
        workspace_root: str = "/app",
    ) -> PersistentExecutionStateEngine:
        if not catalog.complete:
            raise ValueError("persistent execution state requires a complete graph catalog")
        return cls(
            task=task,
            catalog=catalog,
            structural_links=structural_links,
            present_paths=present_paths,
            workspace_root=workspace_root,
        )

    @property
    def snapshot(self) -> PersistentExecutionState:
        return self._snapshot

    @property
    def catalog(self) -> BootstrapCatalog:
        return self._catalog

    @property
    def metrics(self) -> dict[str, int]:
        return dict(self._metrics)

    @property
    def receipts(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(row) for row in self._receipts)

    @staticmethod
    def _certified_links(links: tuple[StructuralLink, ...]) -> tuple[StructuralLink, ...]:
        return tuple(
            sorted(
                (
                    replace(link, relation=normalized_relation)
                    for link in links
                    if (normalized_relation := _certified_relation(link))
                ),
                key=lambda item: (
                    item.source_path,
                    item.target_path,
                    item.relation,
                    item.provenance,
                ),
            )
        )

    def _record(self, boundary: str, **payload: Any) -> None:
        self._receipts.append(
            {
                "boundary": boundary,
                "state_id": self._snapshot.state_id,
                "state_version": self._snapshot.version,
                **payload,
            }
        )

    def _state_path(self, value: Any) -> str:
        raw = str(value or "").strip().replace("\\", "/")
        if raw.startswith(self._workspace_root.rstrip("/") + "/"):
            raw = raw[len(self._workspace_root.rstrip("/")) + 1 :]
        return _path(raw)

    def apply_bootstrap(
        self,
        selection: BootstrapSelection,
        *,
        current_source_revision: str,
        error: bool = False,
    ) -> PersistentExecutionState:
        self._metrics["bootstrap_applications"] += 1
        if current_source_revision != self._snapshot.source_revision:
            self._metrics["stale_rejections"] += 1
            self._record("bootstrap", disposition="stale_source_revision")
            return self._snapshot
        status = BootstrapStatus.SELECTED
        applied = selection
        if not selection.valid:
            status = BootstrapStatus.ERROR_FALLBACK if error else BootstrapStatus.INVALID_FALLBACK
            applied, status = deterministic_bootstrap_fallback(self._catalog, status=status)
        next_snapshot = replace(
            self._snapshot,
            version=self._snapshot.version + 1,
            bootstrap_status=status,
            primary_focus_id=applied.primary_focus_id,
            current_focus_id=applied.primary_focus_id,
            ordered_item_ids=applied.ordered_item_ids,
            risk_item_ids=applied.risk_item_ids,
            validation_item_ids=applied.validation_item_ids,
            last_transition="bootstrap_applied",
        )
        self._snapshot = next_snapshot
        self._metrics["material_transitions"] += 1
        self._record(
            "bootstrap",
            disposition=status.value,
            selected_ids=list(
                dict.fromkeys(
                    (
                        applied.primary_focus_id,
                        *applied.ordered_item_ids,
                        *applied.risk_item_ids,
                        *applied.validation_item_ids,
                    )
                )
            ),
        )
        return self._snapshot

    def project_preflight(
        self,
        proposed: ProposedAction,
        *,
        current_source_revision: str,
    ) -> PreflightStateProjection:
        self._metrics["preflight_projections"] += 1
        targets = tuple(
            dict.fromkeys(
                self._state_path(target.path)
                for target in proposed.targets
                if self._state_path(target.path)
            )
        )
        reasons: list[str] = []
        considered = True
        if proposed.source_revision != current_source_revision:
            considered = False
            reasons.append("stale_proposed_revision")
        if self._snapshot.source_revision != current_source_revision:
            considered = False
            reasons.append("stale_state_revision")
        if not considered:
            self._metrics["stale_rejections"] += 1
        open_obligations = tuple(
            item.obligation_id
            for item in self._snapshot.obligations
            if item.status is ObligationStatus.OPEN
        )
        blocking_obligations = tuple(
            item.obligation_id
            for item in self._snapshot.obligations
            if item.status is ObligationStatus.OPEN and item.blocking
        )
        contradiction = bool(
            considered
            and proposed.operation is ActionOperation.SUBMIT
            and (blocking_obligations or self._snapshot.current_failure is not None)
        )
        if contradiction:
            reasons.append("submit_has_certified_open_state")
        projection = PreflightStateProjection(
            action_id=proposed.action_id,
            considered=considered,
            operation=proposed.operation.value,
            target_paths=targets,
            open_obligation_ids=open_obligations,
            blocking_obligation_ids=blocking_obligations,
            material_contradiction=contradiction,
            reason_codes=tuple(reasons),
            state_version=self._snapshot.version,
        )
        self._record("preflight", **projection.as_dict())
        return projection

    @staticmethod
    def _diagnostic_summary(output: str) -> str:
        for line in str(output or "").splitlines():
            clean = _bounded(line, 280)
            if clean:
                return clean
        return "validation failed without a diagnostic"

    def _open_adjacent_obligations(
        self,
        changed_paths: tuple[str, ...],
        *,
        source_revision: str,
        obligations: tuple[StateObligation, ...] | None = None,
    ) -> tuple[StateObligation, ...]:
        existing = {
            item.obligation_id: item
            for item in (self._snapshot.obligations if obligations is None else obligations)
        }
        changed = frozenset(changed_paths)
        for link in self._links:
            if link.source_path in changed:
                source_path, target_path = link.source_path, link.target_path
            elif link.target_path in changed:
                source_path, target_path = link.target_path, link.source_path
            else:
                continue
            kind = (
                "validate_related_test"
                if link.relation == "test_assertion"
                else "inspect_dependency"
            )
            obligation_id = _stable_id("obligation", kind, source_path, target_path, link.relation)
            existing[obligation_id] = StateObligation(
                obligation_id=obligation_id,
                kind=kind,
                path=target_path,
                relation=link.relation,
                source_path=source_path,
                blocking=False,
                opened_revision=source_revision,
            )
        return tuple(
            sorted(
                existing.values(),
                key=lambda item: (
                    0 if item.status is ObligationStatus.OPEN else 1,
                    not item.blocking,
                    item.kind,
                    item.path,
                    item.obligation_id,
                ),
            )[:32]
        )

    @staticmethod
    def _satisfy_paths(
        obligations: tuple[StateObligation, ...],
        paths: frozenset[str],
        *,
        source_revision: str,
        kinds: frozenset[str],
    ) -> tuple[StateObligation, ...]:
        return tuple(
            replace(
                item,
                status=ObligationStatus.SATISFIED,
                satisfied_revision=source_revision,
            )
            if item.status is ObligationStatus.OPEN and item.kind in kinds and item.path in paths
            else item
            for item in obligations
        )

    def commit_postflight(
        self,
        proposed: ProposedAction,
        *,
        returncode: int,
        output: str,
        changed_paths: tuple[str, ...],
        graph_changed_paths: tuple[str, ...] | None = None,
        current_source_revision: str,
        current_graph_revision: str,
        current_graph_source_revision: str | None = None,
        validation_status: str,
        validation_check_id: str | None = None,
    ) -> PersistentExecutionState:
        self._metrics["postflight_commits"] += 1
        if proposed.source_revision != self._snapshot.source_revision:
            self._metrics["stale_rejections"] += 1
            self._record(
                "postflight",
                action_id=proposed.action_id,
                disposition="stale_proposed_revision",
            )
            return self._snapshot

        targets = frozenset(
            self._state_path(target.path)
            for target in proposed.targets
            if self._state_path(target.path)
        )
        normalized_changed = tuple(
            dict.fromkeys(
                self._state_path(path) for path in changed_paths if self._state_path(path)
            )
        )
        normalized_graph_changed = tuple(
            dict.fromkeys(
                self._state_path(path)
                for path in (changed_paths if graph_changed_paths is None else graph_changed_paths)
                if self._state_path(path)
            )
        )
        files_inspected = self._snapshot.files_inspected
        files_modified = self._snapshot.files_modified
        obligations = self._snapshot.obligations
        validation = self._snapshot.validation
        failure = self._snapshot.current_failure
        phase = self._snapshot.phase
        current_focus_id = self._snapshot.current_focus_id
        current_focus_path = self._snapshot.current_focus_path
        transition = "postflight_observed"

        focus_paths = tuple(normalized_changed) or tuple(sorted(targets))
        if focus_paths and proposed.operation in {
            ActionOperation.READ,
            ActionOperation.EDIT,
            ActionOperation.CREATE,
            ActionOperation.DELETE,
        }:
            current_focus_path = focus_paths[0]
            matched_focus = next(
                (item.item_id for item in self._catalog.items if item.path == current_focus_path),
                "",
            )
            current_focus_id = matched_focus

        if proposed.operation is ActionOperation.READ and returncode == 0:
            files_inspected = tuple(sorted(set(files_inspected) | targets))
            obligations = self._satisfy_paths(
                obligations,
                targets,
                source_revision=current_source_revision,
                kinds=frozenset({"inspect_dependency"}),
            )
            transition = "repository_path_inspected"
        elif proposed.operation is ActionOperation.SEARCH and returncode == 0:
            phase = StatePhase.LOCALIZING
            transition = "search_observed"

        if normalized_changed:
            files_modified = tuple(sorted(set(files_modified) | set(normalized_changed)))
            obligations = self._satisfy_paths(
                obligations,
                frozenset(normalized_changed),
                source_revision=current_source_revision,
                kinds=frozenset({"produce_deliverable", "inspect_dependency"}),
            )
            if not normalized_graph_changed:
                phase = StatePhase.IMPLEMENTING
                transition = "deliverable_changed"
        if normalized_graph_changed:
            obligations = self._open_adjacent_obligations(
                normalized_graph_changed,
                source_revision=current_source_revision,
                obligations=obligations,
            )
            validation = StateValidation(
                status=StateValidationStatus.PENDING,
                source_revision=current_source_revision,
                action_id=proposed.action_id,
            )
            failure = None
            phase = StatePhase.IMPLEMENTING
            transition = "source_changed"

        normalized_validation = str(validation_status or "unknown").strip().lower()
        if proposed.operation is ActionOperation.VALIDATE:
            command = _bounded(proposed.raw_command, 280)
            # The central agent classifies validation exactly once.  Reuse its
            # canonical declared-check identity here instead of reparsing or
            # requiring byte-for-byte equality with a wrapper/redirection-rich
            # Bash command.
            completed_check = _bounded(validation_check_id, 280) or command
            if normalized_validation == StateValidationStatus.PASS.value and returncode == 0:
                validation = StateValidation(
                    status=StateValidationStatus.PASS,
                    command=command,
                    source_revision=current_source_revision,
                    action_id=proposed.action_id,
                )
                declared_scope = any(
                    item.kind is CatalogItemKind.VALIDATION and completed_check in item.anchors
                    for item in self._catalog.items
                )
                validation_targets = targets
                if declared_scope:
                    validation_targets = validation_targets | frozenset(
                        item.path for item in obligations if item.kind == "validate_related_test"
                    )
                obligations = self._satisfy_paths(
                    obligations,
                    validation_targets,
                    source_revision=current_source_revision,
                    kinds=frozenset({"validate_related_test"}),
                )
                obligations = tuple(
                    replace(
                        item,
                        status=ObligationStatus.SATISFIED,
                        satisfied_revision=current_source_revision,
                    )
                    if item.status is ObligationStatus.OPEN
                    and item.kind == "run_validation"
                    and item.source_path == completed_check
                    else item
                    for item in obligations
                )
                failure = None
                phase = (
                    StatePhase.READY_TO_SUBMIT
                    if files_modified
                    and not any(
                        item.status is ObligationStatus.OPEN and item.blocking
                        for item in obligations
                    )
                    else StatePhase.VALIDATING
                )
                transition = "validation_passed"
            elif normalized_validation == StateValidationStatus.FAIL.value:
                validation = StateValidation(
                    status=StateValidationStatus.FAIL,
                    command=command,
                    source_revision=current_source_revision,
                    action_id=proposed.action_id,
                )
                failure = StateFailure(
                    action_id=proposed.action_id,
                    operation=proposed.operation.value,
                    diagnostic=self._diagnostic_summary(output),
                    source_revision=current_source_revision,
                )
                phase = StatePhase.VALIDATING
                transition = "validation_failed"
            else:
                # A recognized validation-shaped action whose terminal result is
                # not mechanically attributable remains pending.  Raw exit code
                # is not enough to manufacture PASS/FAIL authority.
                validation = StateValidation(
                    status=StateValidationStatus.PENDING,
                    command=command,
                    source_revision=current_source_revision,
                    action_id=proposed.action_id,
                )
                phase = StatePhase.VALIDATING
                transition = "validation_outcome_unattributed"

        bound_graph_source_revision = str(
            current_graph_source_revision or self._snapshot.graph_source_revision
        )
        candidate = replace(
            self._snapshot,
            source_revision=current_source_revision,
            graph_source_revision=bound_graph_source_revision,
            graph_current=(
                not normalized_graph_changed
                and self._snapshot.graph_current
                and bound_graph_source_revision == self._snapshot.graph_source_revision
                and current_graph_revision == self._snapshot.graph_revision
            ),
            phase=phase,
            current_focus_id=current_focus_id,
            current_focus_path=current_focus_path,
            files_inspected=files_inspected,
            files_modified=files_modified,
            obligations=obligations,
            validation=validation,
            current_failure=failure,
            last_transition=transition,
        )
        if candidate != self._snapshot:
            candidate = replace(candidate, version=self._snapshot.version + 1)
            self._metrics["material_transitions"] += 1
        self._snapshot = candidate
        self._record(
            "postflight",
            action_id=proposed.action_id,
            disposition="committed",
            operation=proposed.operation.value,
            changed_paths=list(normalized_changed),
            graph_changed_paths=list(normalized_graph_changed),
            returncode=int(returncode),
            validation_status=normalized_validation,
            transition=transition,
        )
        return self._snapshot

    def rebase_graph(
        self,
        *,
        evidence: RepositoryEvidence,
        structural_links: tuple[StructuralLink, ...],
        current_source_revision: str,
        current_graph_revision: str,
        graph_complete: bool,
        current_graph_source_revision: str | None = None,
        changed_paths: tuple[str, ...] = (),
        present_paths: tuple[str, ...] | None = None,
    ) -> PersistentExecutionState:
        self._metrics["graph_rebases"] += 1
        if not graph_complete or not evidence.substrate_ready:
            self._record("graph_rebase", disposition="graph_incomplete")
            return self._snapshot
        if not current_source_revision or not current_graph_revision:
            self._record("graph_rebase", disposition="revision_missing")
            return self._snapshot
        bound_graph_source_revision = str(current_graph_source_revision or current_source_revision)
        if evidence.source_revision and evidence.source_revision != bound_graph_source_revision:
            self._metrics["stale_rejections"] += 1
            self._record("graph_rebase", disposition="evidence_source_revision_mismatch")
            return self._snapshot
        self._links = self._certified_links(structural_links)
        if present_paths is not None:
            self._present_paths = frozenset(
                self._state_path(path) for path in present_paths if self._state_path(path)
            )
        obligations = tuple(
            replace(item, status=ObligationStatus.INVALIDATED)
            if item.relation != "task_requirement"
            and item.status is ObligationStatus.OPEN
            and item.path not in self._present_paths
            else item
            for item in self._snapshot.obligations
        )
        normalized_changed = tuple(
            dict.fromkeys(
                self._state_path(path) for path in changed_paths if self._state_path(path)
            )
        )
        if normalized_changed:
            obligations = self._open_adjacent_obligations(
                normalized_changed,
                source_revision=current_source_revision,
                obligations=obligations,
            )
        required_ids = frozenset(item.item_id for item in self._catalog.items if item.required)
        current_focus_id = (
            self._snapshot.current_focus_id
            if self._snapshot.current_focus_id in required_ids
            else ""
        )
        current_focus_path = self._snapshot.current_focus_path
        if current_focus_path and current_focus_path not in self._present_paths:
            current_focus_path = ""
        candidate = replace(
            self._snapshot,
            source_revision=current_source_revision,
            graph_source_revision=bound_graph_source_revision,
            graph_revision=current_graph_revision,
            graph_current=True,
            current_focus_id=current_focus_id,
            current_focus_path=current_focus_path,
            ordered_item_ids=tuple(
                item_id for item_id in self._snapshot.ordered_item_ids if item_id in required_ids
            ),
            risk_item_ids=tuple(
                item_id for item_id in self._snapshot.risk_item_ids if item_id in required_ids
            ),
            validation_item_ids=tuple(
                item_id for item_id in self._snapshot.validation_item_ids if item_id in required_ids
            ),
            obligations=obligations,
            last_transition="graph_rebased",
        )
        if candidate != self._snapshot:
            candidate = replace(candidate, version=self._snapshot.version + 1)
            self._metrics["material_transitions"] += 1
        self._snapshot = candidate
        self._record("graph_rebase", disposition="current")
        return self._snapshot

    def _item(self, item_id: str) -> BootstrapCatalogItem | None:
        return next((item for item in self._catalog.items if item.item_id == item_id), None)

    def _frame_lines(self, kind: ContextFrameKind) -> list[tuple[str, str]]:
        snapshot = self._snapshot
        focus_id = snapshot.current_focus_id
        if not focus_id and snapshot.graph_revision == self._catalog.graph_revision:
            focus_id = snapshot.primary_focus_id
        focus = self._item(focus_id)
        lines: list[tuple[str, str]] = [
            (
                _stable_id("state-claim", "phase", snapshot.phase.value, snapshot.source_revision),
                f"Phase: {snapshot.phase.value}.",
            )
        ]
        if focus is not None:
            focus_prefix = (
                "Current certified focus"
                if focus.certified
                else "Current bootstrap-selected ranked focus"
            )
            lines.append(
                (
                    _stable_id("state-claim", "focus", focus.item_id),
                    f"{focus_prefix}: {focus.label}.",
                )
            )
            if (
                focus.source_excerpt
                and focus.source_claim_id
                and focus.path not in snapshot.files_inspected
            ):
                support_label = (
                    "certified path/symbol identity"
                    if focus.certified
                    else "ranked relevance; checkout source identity certified"
                )
                lines.append(
                    (
                        focus.source_claim_id,
                        (
                            "Bootstrap-selected repository context "
                            f"[{support_label}] {focus.path}:"
                            f"{focus.source_start_line}-{focus.source_end_line}\n"
                            "```\n"
                            f"{focus.source_excerpt}\n"
                            "```"
                        ),
                    )
                )
        elif snapshot.current_focus_path:
            lines.append(
                (
                    _stable_id("state-claim", "focus-path", snapshot.current_focus_path),
                    f"Current observed repository focus: {snapshot.current_focus_path}.",
                )
            )
        open_obligations = [
            item for item in snapshot.obligations if item.status is ObligationStatus.OPEN
        ]
        for obligation in open_obligations[:4]:
            obligation_target = obligation.path or obligation.source_path
            lines.append(
                (
                    _stable_id("state-claim", obligation.obligation_id, snapshot.source_revision),
                    (
                        f"{'Required' if obligation.blocking else 'Related'} "
                        f"{obligation.kind}: {obligation_target} "
                        f"({obligation.relation} from {obligation.source_path})."
                    ),
                )
            )
        if snapshot.validation.status is not StateValidationStatus.UNKNOWN:
            validation_text = f"Validation: {snapshot.validation.status.value}"
            if snapshot.validation.command:
                validation_text += f" - {snapshot.validation.command}"
            lines.append(
                (
                    _stable_id(
                        "state-claim",
                        "validation",
                        snapshot.validation.status.value,
                        snapshot.validation.source_revision,
                    ),
                    validation_text + ".",
                )
            )
        if snapshot.current_failure is not None:
            lines.append(
                (
                    _stable_id(
                        "state-claim",
                        "failure",
                        snapshot.current_failure.action_id,
                        snapshot.current_failure.diagnostic,
                    ),
                    f"Current validation failure: {snapshot.current_failure.diagnostic}.",
                )
            )
        if kind in {ContextFrameKind.INITIAL, ContextFrameKind.DELTA, ContextFrameKind.CRITICAL}:
            next_items = [
                self._item(item_id)
                for item_id in snapshot.ordered_item_ids
                if item_id != snapshot.primary_focus_id
            ]
            next_items = [item for item in next_items if item is not None]
            if next_items:
                lines.append(
                    (
                        _stable_id(
                            "state-claim",
                            "ordered",
                            *(item.item_id for item in next_items[:3]),
                        ),
                        "Bootstrap-selected next items: "
                        + "; ".join(item.label for item in next_items[:3])
                        + ".",
                    )
                )
        return lines

    def compile_context(
        self,
        *,
        current_source_revision: str,
        provider_call: int,
        max_tokens: int,
        token_counter: Callable[[str], int] = _default_token_counter,
    ) -> PersistentContextFrame:
        self._metrics["context_compilations"] += 1
        if current_source_revision != self._snapshot.source_revision:
            self._metrics["stale_rejections"] += 1
            frame = PersistentContextFrame(
                kind=ContextFrameKind.NONE,
                rendered_text="",
                claim_ids=(),
                state_version=self._snapshot.version,
                source_revision=current_source_revision,
                provider_call=provider_call,
                token_count=0,
                reason_codes=("stale_source_revision",),
            )
            self._record("provider_context", **frame.as_dict())
            return frame
        if self._snapshot.bootstrap_status is not BootstrapStatus.SELECTED:
            frame = PersistentContextFrame(
                kind=ContextFrameKind.NONE,
                rendered_text="",
                claim_ids=(),
                state_version=self._snapshot.version,
                source_revision=current_source_revision,
                provider_call=provider_call,
                token_count=0,
                reason_codes=("bootstrap_selection_unavailable",),
            )
            self._record("provider_context", **frame.as_dict())
            return frame
        if not self._snapshot.graph_current:
            frame = PersistentContextFrame(
                kind=ContextFrameKind.NONE,
                rendered_text="",
                claim_ids=(),
                state_version=self._snapshot.version,
                source_revision=current_source_revision,
                provider_call=provider_call,
                token_count=0,
                reason_codes=("graph_rebase_required",),
            )
            self._record("provider_context", **frame.as_dict())
            return frame
        if max_tokens < 1:
            frame = PersistentContextFrame(
                kind=ContextFrameKind.NONE,
                rendered_text="",
                claim_ids=(),
                state_version=self._snapshot.version,
                source_revision=current_source_revision,
                provider_call=provider_call,
                token_count=0,
                reason_codes=("context_budget_closed",),
            )
            self._record("provider_context", **frame.as_dict())
            return frame

        if self._snapshot.current_failure is not None:
            kind = ContextFrameKind.CRITICAL
        elif self._last_compiled_version == 0:
            kind = ContextFrameKind.INITIAL
        elif self._last_compiled_version != self._snapshot.version:
            kind = ContextFrameKind.DELTA
        else:
            kind = ContextFrameKind.CORE
        ceiling = min(
            max_tokens,
            512 if kind in {ContextFrameKind.INITIAL, ContextFrameKind.CRITICAL} else 256,
        )
        if kind is ContextFrameKind.CORE:
            ceiling = min(ceiling, 96)
        header = "GroundTruth execution state (deterministic, repository-grounded):"
        selected: list[str] = []
        claim_ids: list[str] = []
        for claim_id, line in self._frame_lines(kind):
            candidate = "\n".join((header, *selected, line))
            if token_counter(candidate) > ceiling:
                continue
            # Independent byte bound prevents a pathological tokenizer mismatch.
            if len(candidate.encode("utf-8")) > 4_096:
                continue
            selected.append(line)
            claim_ids.append(claim_id)
        rendered = "\n".join((header, *selected)) if selected else ""
        token_count = token_counter(rendered) if rendered else 0
        reason_codes = () if rendered else ("no_complete_state_fact_within_budget",)
        focus_id = self._snapshot.current_focus_id or self._snapshot.primary_focus_id
        focus = self._item(focus_id)
        selected_evidence: tuple[dict[str, Any], ...] = ()
        if focus is not None and focus.source_claim_id and focus.source_claim_id in claim_ids:
            selected_evidence = (
                {
                    "path": focus.path,
                    "start_line": focus.source_start_line,
                    "end_line": focus.source_end_line,
                    "symbol": focus.symbol,
                    "claim_id": focus.source_claim_id,
                    "support_kind": (
                        "certified_identity" if focus.certified else "bootstrap_ranked_candidate"
                    ),
                    "retrieval_rank": focus.retrieval_rank,
                    "supporting_channels": list(focus.support_channels),
                },
            )
        frame = PersistentContextFrame(
            kind=kind if rendered else ContextFrameKind.NONE,
            rendered_text=rendered,
            claim_ids=tuple(claim_ids),
            state_version=self._snapshot.version,
            source_revision=current_source_revision,
            provider_call=provider_call,
            token_count=token_count,
            reason_codes=reason_codes,
            selected_evidence=selected_evidence,
        )
        self._last_compiled_version = self._snapshot.version
        self._record("provider_context", **frame.as_dict())
        return frame

    def evaluate_completion(self, *, current_source_revision: str) -> dict[str, Any]:
        open_ids = tuple(
            item.obligation_id
            for item in self._snapshot.obligations
            if item.status is ObligationStatus.OPEN and item.blocking
        )
        advisory_ids = tuple(
            item.obligation_id
            for item in self._snapshot.obligations
            if item.status is ObligationStatus.OPEN and not item.blocking
        )
        ready = bool(
            current_source_revision == self._snapshot.source_revision
            and self._snapshot.files_modified
            and self._snapshot.validation.status is StateValidationStatus.PASS
            and self._snapshot.validation.source_revision == current_source_revision
            and not open_ids
            and self._snapshot.current_failure is None
        )
        receipt = {
            "ready": ready,
            "source_revision": current_source_revision,
            "open_obligation_ids": list(open_ids),
            "open_advisory_ids": list(advisory_ids),
            "validation_status": self._snapshot.validation.status.value,
            "state_version": self._snapshot.version,
        }
        self._record("completion", **receipt)
        return receipt


__all__ = [
    "BootstrapCatalog",
    "BootstrapCatalogItem",
    "BootstrapSelection",
    "BootstrapStatus",
    "CatalogItemKind",
    "ContextFrameKind",
    "ObligationStatus",
    "PERSISTENT_STATE_FIELD_AUTHORITIES",
    "PersistentContextFrame",
    "PersistentExecutionState",
    "PersistentExecutionStateEngine",
    "PreflightStateProjection",
    "StateFieldAuthority",
    "StateObligation",
    "StatePhase",
    "StateValidation",
    "StateValidationStatus",
    "build_bootstrap_catalog",
    "build_bootstrap_messages",
    "bootstrap_visible_item_ids",
    "deterministic_bootstrap_fallback",
    "parse_bootstrap_selection",
]
